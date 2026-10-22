# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Imported report history and authenticated attachment isolation."""

import asyncio
from typed_report_fixtures import typed_client as typed_client
import asyncpg
import auth
import reports
import modules.common as common
from modules.reports import (
    create_report,
    list_reports,
    get_report,
    update_report,
    delete_report,
)
from domain_packages.files import package_file
from domain_packages.importer import import_validated
from domain_packages.middleware import PackageSelectionMiddleware
from domain_packages.storage import VersionStorage
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient
from test_package_resource_api import variant
from test_package_importer import user


def test_reports_preserve_history_and_enforce_selected_owner(
    postgres_url, tmp_path, monkeypatch
):
    for module in (auth, common, reports):
        monkeypatch.setattr(module, "DATABASE_URL", postgres_url)
    monkeypatch.setenv("LUNAR_PACKAGE_STORAGE_ROOT", str(tmp_path / "store"))

    async def setup():
        connection = await asyncpg.connect(postgres_url)
        try:
            owners = [await user(connection), await user(connection)]
            await connection.execute("UPDATE users SET email_verified_at=NOW()")
            versions = []
            identities = []
            for index, owner in enumerate([owners[0], owners[0], owners[1]]):
                context = await import_validated(
                    connection,
                    VersionStorage(tmp_path / "store"),
                    user_id=owner,
                    archive=variant(tmp_path, index),
                )
                versions.append(context)
                identities.append(
                    str(
                        await connection.fetchval(
                            "SELECT id FROM reports WHERE user_id=$1 AND version_id=$2",
                            owner,
                            context.version_id,
                        )
                    )
                )
            return (
                versions,
                identities,
                [await auth.create_session(owner) for owner in owners],
            )
        finally:
            await connection.close()

    versions, identities, tokens = asyncio.run(setup())
    app = Starlette(
        routes=[
            Route("/api/report", list_reports, methods=["GET"]),
            Route("/api/report", create_report, methods=["POST"]),
            Route("/api/report/{report_id}", get_report, methods=["GET"]),
            Route("/api/report/{report_id}", update_report, methods=["PUT"]),
            Route("/api/report/{report_id}", delete_report, methods=["DELETE"]),
            Route("/api/reports/{report_id}", reports.get_report),
            Route("/api/package-files/{file_id}", package_file),
        ]
    )
    app.add_middleware(PackageSelectionMiddleware)
    with TestClient(app) as client:
        assert client.get("/api/reports/" + identities[0]).status_code == 401
        client.cookies.set(auth.SESSION_COOKIE, tokens[0])
        assert client.get("/api/report").status_code == 409
        header = {"X-Lunar-Package-Version": str(versions[0].version_id)}
        listed = client.get("/api/report", headers=header)
        assert listed.status_code == 200, listed.text
        assert len(listed.json()) == 2
        assert all(
            row["version_id"] == str(versions[0].version_id) for row in listed.json()
        )
        assert sum(row["generation_type"] == "prism" for row in listed.json()) == 1
        assert identities[0] in [row["id"] for row in listed.json()]
        path = "/api/report/" + identities[0]
        response = client.get(path, headers=header)
        assert response.status_code == 200, response.text
        original = response.json()
        assert original["version"] == 2 and original["imported"] is True
        assert original["content"] == "![Stock](plot.svg)\nThree boxes."
        assert original["revisions"][0]["content"] == "Two boxes."
        assert original["sections"][0]["run_output_id"]
        attachment = original["attachments"][0]
        assert attachment["link"] == "plot.svg"
        image = client.get(attachment["url"])
        assert image.status_code == 200 and b"<svg" in image.content
        assert (
            client.get(path, headers=header, params={"version": 1}).json()["content"]
            == "Two boxes."
        )
        assert (
            client.get(path, headers=header, params={"version": 99}).status_code == 404
        )
        assert (
            client.get("/api/reports/" + identities[0], headers=header).status_code
            == 200
        )
        for foreign in identities[1:]:
            assert (
                client.get("/api/report/" + foreign, headers=header).status_code == 404
            )
            assert (
                client.get("/api/reports/" + foreign, headers=header).status_code == 404
            )
            assert (
                client.put(
                    "/api/report/" + foreign,
                    headers=header,
                    json={"content": "corrupt"},
                ).status_code
                == 404
            )
            assert (
                client.delete("/api/report/" + foreign, headers=header).status_code
                == 404
            )
        update = client.put(path, headers=header, json={"content": "Four boxes."})
        assert update.status_code == 200, update.text
        assert update.json()["version"] == 3
        current = client.get(path, headers=header).json()
        assert [row["version"] for row in current["revisions"]] == [1, 2]
        assert current["revisions"][1]["content"] == original["content"]
        assert current["attachments"] == original["attachments"]
        assert (
            client.put(path, headers=header, json={"name": "Renamed"}).json()["version"]
            == 3
        )
        assert (
            client.put(
                path, headers=header, json={"provenance_data": {"versions": []}}
            ).status_code
            == 422
        )
        created = client.post(
            "/api/report",
            headers=header,
            json={"name": "Manual", "content": "Five boxes."},
        )
        assert created.status_code == 201, created.text
        assert created.json()["version_id"] == str(versions[0].version_id)
        assert len(client.get("/api/report", headers=header).json()) == 3
        other = {"X-Lunar-Package-Version": str(versions[1].version_id)}
        assert (
            client.get("/api/report/" + created.json()["id"], headers=other).status_code
            == 404
        )
        assert (
            client.delete(
                "/api/report/" + created.json()["id"], headers=header
            ).status_code
            == 200
        )
        assert len(client.get("/api/report", headers=header).json()) == 2


def test_typed_report_persistence_immutability_and_isolation(typed_client):
    client, contexts, ids, documents, _ = typed_client
    for index in (0, 1):
        headers = {"X-Lunar-Package-Version": str(contexts[index].version_id)}
        path = "/api/report/" + ids[index]
        response = client.get(path, headers=headers)
        assert response.status_code == 200, response.text
        report = response.json()
        assert report["typed_report"] == documents[index]["metadata"]["typed_report"]
        assert report["template_snapshot"] == documents[index]["template_snapshot"]
        assert report["read_only"] is True and len(report["sections"]) == 8
        assert (
            client.put(
                path, headers=headers, json={"content": "break tree"}
            ).status_code
            == 409
        )
        assert client.get(report["attachments"][0]["url"]).status_code == 200
        for foreign in set(ids) - {ids[index]}:
            assert (
                client.get("/api/report/" + foreign, headers=headers).status_code == 404
            )
        attachment = report["attachments"][0]
        foreign_url = attachment["url"].replace(
            str(contexts[index].version_id), str(contexts[1 - index].version_id)
        )
        assert client.get(foreign_url).status_code == 404
