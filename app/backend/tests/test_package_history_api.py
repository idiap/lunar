# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Imported run observations retain original bytes and never become executable jobs."""

import asyncio
import hashlib
import json
import asyncpg
import auth
import modules.common as common
from domain_packages.archive import validate_archive
from domain_packages.importer import import_validated
from domain_packages.storage import VersionStorage
from domain_packages.worker.runs import recover_runs
from domain_packages.middleware import PackageSelectionMiddleware
from domain_packages.files import package_file
from prism_runs.routes import (
    prism_run_detail,
    prism_run_artifact,
    prism_reasoning_stream,
)
from prism_runs.reasoning import project_source, source_digest
from provenance.routes import run_provenance
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient
from test_package_archive import write_zip
from test_package_importer import user


def test_original_run_observations_provenance_and_artifact_links(
    postgres_url, tmp_path, monkeypatch
):
    for module in (auth, common):
        monkeypatch.setattr(module, "DATABASE_URL", postgres_url)
    monkeypatch.setenv("LUNAR_PACKAGE_STORAGE_ROOT", str(tmp_path / "store"))
    stamp = "2025-01-02T03:04:05+00:00"
    source = project_source(stage="Original check", status="completed")

    def mutate(manifest, payloads):
        values = dict(payloads)
        report = json.loads(values["reports/stock.json"])
        facts = report["runs"][0]["facts"]
        facts.update(
            created_at=stamp,
            started_at=stamp,
            finished_at=stamp,
            planned_sources=[
                {
                    "resource_id": "stock",
                    "source_local_identifier": "original",
                    "required": True,
                    "binding_metadata": {},
                }
            ],
            consumed_sources=[
                {
                    "resource_id": "stock",
                    "source_local_identifier": "original",
                    "access_point_id": None,
                    "operation_id": None,
                    "access_mode": "fixture",
                    "version_or_snapshot": "v1",
                    "safe_locator": "package:data-sources/shared.csv",
                    "content_digest": "sha256:"
                    + hashlib.sha256(values["data-sources/shared.csv"]).hexdigest(),
                    "observed_at": stamp,
                    "redacted_metadata": {},
                }
            ],
            input_entities=[
                {
                    "input_key": "count",
                    "kind": "scalar",
                    "safe_locator": "input:count",
                    "content_digest": "sha256:" + hashlib.sha256(b"3").hexdigest(),
                    "observed_at": stamp,
                    "redacted_metadata": {},
                }
            ],
            events=[
                {
                    "stage_id": "original-check",
                    "component_id": "stock",
                    "status": "completed",
                    "started_at": stamp,
                    "finished_at": stamp,
                    "safe_summary": "Original check passed",
                    "detail": {},
                }
            ],
            prism_reasoning_entries=[
                {
                    "sequence": 1,
                    "source_event_key": "original:1",
                    "event_kind": "stage",
                    "observed_at": stamp,
                    "source": source.model_dump(),
                    "source_digest": source_digest(source),
                    "presentation": {"status": "pending", "icon_id": "information"},
                }
            ],
            artifacts=[
                {
                    "id": "old-plot",
                    "file": "reports/plot.svg",
                    "source_metadata": {
                        "artifact_key": "plot",
                        "provenance_entity_id": "original:plot",
                    },
                }
            ],
            provenance_receipts=[
                {
                    "file": "reports/original-prov.json",
                    "original_wrapper_digest": "sha256:"
                    + hashlib.sha256(b"original-wrapper").hexdigest(),
                    "generated_at": stamp,
                }
            ],
        )
        values["reports/stock.json"] = json.dumps(report).encode()
        for item in manifest["files"]:
            item.update(
                size=len(values[item["path"]]),
                sha256=hashlib.sha256(values[item["path"]]).hexdigest(),
            )
        return manifest, list(values.items())

    archive = tmp_path / "history.zip"
    write_zip(archive, mutate=mutate)
    staged = validate_archive(archive, tmp_path / "validated")
    expected_plot = (staged.root / "reports/plot.svg").read_bytes()
    expected_provenance = json.loads(
        (staged.root / "reports/original-prov.json").read_bytes()
    )

    async def setup():
        connection = await asyncpg.connect(postgres_url)
        try:
            owner = await user(connection)
            await connection.execute("UPDATE users SET email_verified_at=NOW()")
            context = await import_validated(
                connection,
                VersionStorage(tmp_path / "store"),
                user_id=owner,
                archive=staged,
            )
            run_id = str(
                await connection.fetchval(
                    "SELECT id FROM prism_runs WHERE user_id=$1", owner
                )
            )
            assert await recover_runs(connection) == []
            return context, run_id, await auth.create_session(owner)
        finally:
            await connection.close()

    context, run_id, token = asyncio.run(setup())
    app = Starlette(
        routes=[
            Route("/api/prism/runs/reasoning", prism_reasoning_stream),
            Route("/api/prism/runs/{run_id}", prism_run_detail),
            Route("/api/prism/runs/{run_id}/provenance", run_provenance),
            Route(
                "/api/prism/runs/{run_id}/artifacts/{artifact_id}", prism_run_artifact
            ),
            Route("/api/package-files/{file_id}", package_file),
        ]
    )
    app.add_middleware(PackageSelectionMiddleware)
    with TestClient(app) as client:
        client.cookies.set(auth.SESSION_COOKIE, token)
        header = {"X-Lunar-Package-Version": str(context.version_id)}
        response = client.get("/api/prism/runs/" + run_id, headers=header)
        assert response.status_code == 200, response.text
        run = response.json()
        assert run["imported"] is True and run["created_at"] == stamp
        assert run["original_facts"]["created_at"] == stamp
        assert (
            run["original_facts"]["prism_reasoning_entries"][0]["presentation"][
                "status"
            ]
            == "pending"
        )
        assert run["consumed_sources"][0]["source_local_identifier"] == "original"
        assert run["input_entities"][0]["input_key"] == "count"
        assert run["events"][0]["safe_summary"] == "Original check passed"
        assert client.get(run["artifacts"][0]["url"]).content == expected_plot
        export = client.get(
            "/api/prism/runs/" + run_id + "/provenance",
            headers=header,
            params={"format": "prov-json"},
        )
        assert export.status_code == 200, export.text
        assert export.json()["document"] == expected_provenance
        assert (
            export.json()["digest"]
            == "sha256:" + hashlib.sha256(b"original-wrapper").hexdigest()
        )
        reasoning = client.get(
            "/api/prism/runs/reasoning",
            headers=header,
            params={"workflow_id": run["workflow_id"], "run_ids": run_id},
        )
        assert reasoning.status_code == 200, reasoning.text
        assert (
            "Original check" in reasoning.text
            and "interrupted" in reasoning.text
            and '"type":"done"' in reasoning.text
        )
