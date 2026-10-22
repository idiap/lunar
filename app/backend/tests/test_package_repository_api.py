# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Declared graphs and source bytes are served only from the selected import."""

import asyncio
import hashlib
import json
import asyncpg
import auth
import modules.common as common
from domain_packages.archive import validate_archive
from domain_packages.files import package_file
from domain_packages.importer import import_validated
from domain_packages.middleware import PackageSelectionMiddleware
from domain_packages.repository_routes import repository_catalog, repository_bundle
from domain_packages.storage import VersionStorage
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient
from test_package_archive import write_zip
from test_package_importer import user


def test_repository_graph_source_and_integrity(postgres_url, tmp_path, monkeypatch):
    for module in (auth, common):
        monkeypatch.setattr(module, "DATABASE_URL", postgres_url)
    monkeypatch.setenv("LUNAR_PACKAGE_STORAGE_ROOT", str(tmp_path / "store"))

    def archive(index):
        def mutate(manifest, payloads):
            values = dict(payloads)
            document = json.loads(values["repository/warehouse.json"])
            document["metadata"].update(catalog="repository/catalog.json")
            values["repository/warehouse.json"] = json.dumps(document).encode()
            values["repository/catalog.json"] = json.dumps(
                {
                    "schema_version": 1,
                    "visibility": "package",
                    "modules": [{"id": "stock", "name": str(index)}],
                    "skills": [],
                }
            ).encode()
            values["repository/main.prism"] = (
                "type Count = (value: Int) -> Int\nreasoning count"
                + str(index)
                + "(request: Int) -> Int:\n    [result: Count(request)]\n    return result\n"
            ).encode()
            manifest["collections"]["repository"][0]["files"] = [
                "repository/catalog.json",
                "repository/main.prism",
            ]
            manifest["files"] = [
                {
                    "path": path,
                    "size": len(content),
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "media_type": (
                        "text/plain" if path.endswith(".prism") else "application/json"
                    ),
                }
                for path, content in values.items()
            ]
            return manifest, list(values.items())

        path = tmp_path / (str(index) + ".zip")
        write_zip(path, mutate=mutate)
        return validate_archive(path, tmp_path / (str(index) + "-validated"))

    async def setup():
        connection = await asyncpg.connect(postgres_url)
        try:
            owners = [await user(connection), await user(connection)]
            await connection.execute("UPDATE users SET email_verified_at=NOW()")
            versions = [
                await import_validated(
                    connection,
                    VersionStorage(tmp_path / "store"),
                    user_id=owner,
                    archive=archive(index),
                )
                for index, owner in enumerate([owners[0], owners[0], owners[1]])
            ]
            return versions, await auth.create_session(owners[0])
        finally:
            await connection.close()

    versions, token = asyncio.run(setup())
    app = Starlette(
        routes=[
            Route("/api/repository/catalog", repository_catalog),
            Route("/api/repository/bundle", repository_bundle),
            Route("/api/package-files/{file_id}", package_file),
        ]
    )
    app.add_middleware(PackageSelectionMiddleware)
    with TestClient(app) as client:
        client.cookies.set(auth.SESSION_COOKIE, token)
        for index in range(2):
            header = {"X-Lunar-Package-Version": str(versions[index].version_id)}
            catalog = client.get("/api/repository/catalog", headers=header)
            assert catalog.status_code == 200, catalog.text
            assert catalog.json()["modules"][0]["name"] == str(index)
            bundle = client.get("/api/repository/bundle", headers=header)
            assert bundle.status_code == 200, bundle.text
            assert bundle.json()["projects"][0]["workflows"][0]["graph"][
                "reasoning"
            ] == "count" + str(index)
            source = next(
                row
                for row in catalog.json()["resources"][0]["files"]
                if row["path"].endswith(".prism")
            )
            assert "reasoning count" + str(index) in client.get(source["url"]).text
        foreign = {"X-Lunar-Package-Version": str(versions[2].version_id)}
        assert client.get("/api/repository/catalog", headers=foreign).status_code == 404
        VersionStorage(tmp_path / "store").package_file(
            versions[0], "repository/catalog.json"
        ).write_bytes(b"{}")
        assert (
            client.get(
                "/api/repository/catalog",
                headers={"X-Lunar-Package-Version": str(versions[0].version_id)},
            ).status_code
            == 409
        )
