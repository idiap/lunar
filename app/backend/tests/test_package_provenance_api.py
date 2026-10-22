# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Standards provenance and template bindings stay within one owned version."""

import asyncio
from typed_report_fixtures import typed_client as typed_client
import uuid
import asyncpg
import auth
import modules.common as common
from domain_packages.importer import import_validated
from domain_packages.middleware import PackageSelectionMiddleware
from domain_packages.storage import VersionStorage
from provenance.service import persist_run_provenance
from provenance.routes import run_provenance
from reporting.routes import (
    template_outputs,
    run_template,
    generated_report_provenance,
    report_section_provenance,
)
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient
from test_package_resource_api import variant
from test_package_importer import user


def test_provenance_formats_and_template_binding_isolation(
    postgres_url, tmp_path, monkeypatch
):
    for module in (auth, common):
        monkeypatch.setattr(module, "DATABASE_URL", postgres_url)

    async def setup():
        connection = await asyncpg.connect(postgres_url)
        try:
            owners = [await user(connection), await user(connection)]
            await connection.execute("UPDATE users SET email_verified_at=NOW()")
            contexts = []
            runs = []
            outputs = []
            reports = []
            for index, owner in enumerate([owners[0], owners[0], owners[1]]):
                context = await import_validated(
                    connection,
                    VersionStorage(tmp_path / "store"),
                    user_id=owner,
                    archive=variant(tmp_path, index),
                )
                contexts.append(context)
                run = await connection.fetchrow(
                    "SELECT id,workflow_id FROM prism_runs WHERE user_id=$1 AND version_id=$2",
                    owner,
                    context.version_id,
                )
                runs.append(str(run["id"]))
                await persist_run_provenance(
                    connection,
                    context,
                    run["id"],
                    {"id": run["workflow_id"], "name": "Stock"},
                    failed=False,
                )
                outputs.append(
                    str(
                        await connection.fetchval(
                            "UPDATE prism_run_outputs SET output_key='stock' WHERE run_id=$1 RETURNING id",
                            run["id"],
                        )
                    )
                )
                reports.append(
                    str(
                        await connection.fetchval(
                            "SELECT id FROM reports WHERE user_id=$1 AND version_id=$2",
                            owner,
                            context.version_id,
                        )
                    )
                )
            template = uuid.uuid4()
            await connection.execute(
                "INSERT INTO templates(id,user_id,name,content) VALUES($1,$2,'Summary','{{stock}}')",
                template,
                owners[0],
            )
            return (
                contexts,
                runs,
                outputs,
                reports,
                str(template),
                await auth.create_session(owners[0]),
            )
        finally:
            await connection.close()

    contexts, runs, outputs, reports, template, token = asyncio.run(setup())
    app = Starlette(
        routes=[
            Route("/api/prism/runs/{run_id}/provenance", run_provenance),
            Route("/api/templates/{template_id}/outputs", template_outputs),
            Route("/api/templates/{template_id}/runs", run_template, methods=["POST"]),
            Route("/api/report/{report_id}/provenance", generated_report_provenance),
            Route(
                "/api/report/{report_id}/sections/{section_id}/provenance",
                report_section_provenance,
            ),
        ]
    )
    app.add_middleware(PackageSelectionMiddleware)
    with TestClient(app) as client:
        client.cookies.set(auth.SESSION_COOKIE, token)
        header = {"X-Lunar-Package-Version": str(contexts[0].version_id)}
        for fmt in ("prov-json", "json-ld"):
            own = client.get(
                "/api/prism/runs/" + runs[0] + "/provenance",
                headers=header,
                params={"format": fmt},
            )
            assert own.status_code == 200, own.text
            assert own.json()["format"] == fmt and own.json()["document"]
            for other in runs[1:]:
                assert (
                    client.get(
                        "/api/prism/runs/" + other + "/provenance",
                        headers=header,
                        params={"format": fmt},
                    ).status_code
                    == 404
                )
            imported = client.get(
                "/api/report/" + reports[0] + "/provenance",
                headers=header,
                params={"format": fmt},
            )
            assert imported.status_code == (
                200 if fmt == "prov-json" else 409
            ), imported.text
            if fmt == "prov-json":
                assert imported.json()["format"] == fmt
            for other in reports[1:]:
                assert (
                    client.get(
                        "/api/report/" + other + "/provenance",
                        headers=header,
                        params={"format": fmt},
                    ).status_code
                    == 404
                )
        inventory = client.get(
            "/api/templates/" + template + "/outputs", headers=header
        )
        assert inventory.status_code == 200, inventory.text
        assert [row["id"] for row in inventory.json()["items"]] == [outputs[0]]
        for output in outputs[1:]:
            rejected = client.post(
                "/api/templates/" + template + "/runs",
                headers=header,
                json={"report_name": "Summary", "bindings": {"stock": output}},
            )
            assert rejected.status_code == 422, rejected.text
        created = client.post(
            "/api/templates/" + template + "/runs",
            headers=header,
            json={"report_name": "Summary", "bindings": {"stock": outputs[0]}},
        )
        assert created.status_code == 201, created.text
        report = created.json()["report_id"]
        provenance = client.get("/api/report/" + report + "/provenance", headers=header)
        assert provenance.status_code == 200, provenance.text
        assert provenance.json()["report"]["version_id"] == str(contexts[0].version_id)
        section = provenance.json()["sections"][0]
        assert section["run_id"] == runs[0] and section["run_output_id"] == outputs[0]
        sliced = client.get(
            "/api/report/"
            + report
            + "/sections/"
            + section["section_id"]
            + "/provenance",
            headers=header,
        )
        assert sliced.status_code == 200, sliced.text
        assert sliced.json()["graph"]["nodes"]
        for fmt in ("prov-json", "json-ld"):
            assert (
                client.get(
                    "/api/report/" + report + "/provenance",
                    headers=header,
                    params={"format": fmt},
                ).json()["format"]
                == fmt
            )
        other = {"X-Lunar-Package-Version": str(contexts[1].version_id)}
        assert (
            client.get(
                "/api/report/" + report + "/provenance", headers=other
            ).status_code
            == 404
        )


def test_each_typed_section_resolves_its_native_ancestry(typed_client):
    from reporting.service import slice_prov_document

    client, contexts, ids, documents, _ = typed_client
    headers = {"X-Lunar-Package-Version": str(contexts[0].version_id)}
    typed = documents[0]["metadata"]["typed_report"]
    for section, mapping in typed["sections"].items():
        path = f"/api/report/{ids[0]}/sections/{section}/provenance"
        response = client.get(path, headers=headers)
        assert response.status_code == 200, response.text
        value = response.json()
        assert value["native_reference"] == mapping["reference"]
        assert value["recorded_execution"] == typed["native"]["run_id"]
        sliced = slice_prov_document(typed["provenance"], mapping["entity"])
        assert {node["id"] for node in value["graph"]["nodes"]} == set(
            sliced["entity"]
        ) | set(sliced["activity"])
        for foreign in ids[1:]:
            assert (
                client.get(path.replace(ids[0], foreign), headers=headers).status_code
                == 404
            )
    markdown = typed["sections"]["markdown"]["entity"]
    html = typed["sections"]["html"]["entity"]
    assert html not in slice_prov_document(typed["provenance"], markdown)["entity"]
