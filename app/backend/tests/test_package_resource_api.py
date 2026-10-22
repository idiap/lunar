# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Skills, sources and verified file downloads share one authenticated selection."""

import asyncio
import hashlib
import json
from urllib.parse import urlsplit

import asyncpg
import auth
import modules.common as common
from data_sources.routes import data_source_list, data_source_detail
from domain_packages.archive import validate_archive
from domain_packages.files import package_file, package_file_options
from domain_packages.importer import import_validated
from domain_packages.middleware import PackageSelectionMiddleware
from domain_packages.storage import VersionStorage
from skills.routes import skill_list, skill_detail
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient
from test_package_archive import write_zip
from test_package_importer import user


def variant(tmp_path, index):
    def change(manifest, payloads):
        values = dict(payloads)
        for path in ("skills/stock.json", "data-sources/stock.json"):
            document = json.loads(values[path])
            document["name"] += " selection-" + str(index)
            if path.startswith("skills/"):
                document["instructions"] = "Instructions for selection-" + str(index)
            else:
                document["descriptor"]["visibility"] = "internal"
            values[path] = json.dumps(document).encode()
        for row in manifest["files"]:
            row.update(
                size=len(values[row["path"]]),
                sha256=hashlib.sha256(values[row["path"]]).hexdigest(),
            )
        return manifest, list(values.items())

    archive = tmp_path / (str(index) + ".zip")
    write_zip(archive, mutate=change)
    return validate_archive(archive, tmp_path / (str(index) + "-validated"))


def test_resource_queries_and_downloads_are_version_scoped(
    postgres_url, tmp_path, monkeypatch
):
    monkeypatch.setattr(auth, "DATABASE_URL", postgres_url)
    monkeypatch.setattr(common, "DATABASE_URL", postgres_url)
    monkeypatch.setenv("LUNAR_PACKAGE_STORAGE_ROOT", str(tmp_path / "store"))

    async def setup():
        connection = await asyncpg.connect(postgres_url)
        try:
            owners = [await user(connection), await user(connection)]
            await connection.execute("UPDATE users SET email_verified_at=NOW()")
            versions = []
            for index, owner in enumerate([owners[0], owners[0], owners[1]]):
                versions.append(
                    await import_validated(
                        connection,
                        VersionStorage(tmp_path / "store"),
                        user_id=owner,
                        archive=variant(tmp_path, index),
                    )
                )
            return versions, [await auth.create_session(owner) for owner in owners]
        finally:
            await connection.close()

    versions, tokens = asyncio.run(setup())
    app = Starlette(
        routes=[
            Route("/api/skills", skill_list),
            Route("/api/skills/{skill_id}", skill_detail),
            Route("/api/data-sources", data_source_list),
            Route("/api/data-sources/{resource_id}", data_source_detail),
            Route("/api/package-files", package_file_options),
            Route("/api/package-files/{file_id}", package_file),
        ]
    )
    app.add_middleware(PackageSelectionMiddleware)
    with TestClient(app) as client:
        assert client.get("/api/skills").status_code == 401
        assert client.get("/api/package-files").status_code == 401
        client.cookies.set(auth.SESSION_COOKIE, tokens[0])
        assert client.get("/api/skills").status_code == 409
        assert client.get("/api/package-files").status_code == 409
        file_urls = []
        for index, context in enumerate(versions):
            client.cookies.set(auth.SESSION_COOKIE, tokens[0 if index < 2 else 1])
            header = {"X-Lunar-Package-Version": str(context.version_id)}
            skills = client.get("/api/skills", headers=header)
            assert skills.status_code == 200, skills.text
            assert (
                skills.json()["total"] == 1
                and skills.json()["items"][0]["groups"] == []
            )
            assert skills.json()["items"][0][
                "display_name"
            ] == "Stock summary selection-" + str(index)
            assert (
                client.get(
                    "/api/skills",
                    headers=header,
                    params={"q": "selection-" + str((index + 1) % 3)},
                ).json()["total"]
                == 0
            )
            skill = client.get("/api/skills/stock", headers=header).json()
            assert skill["instructions"] == "Instructions for selection-" + str(index)
            assert skill["capabilities"] == [{"operation": "summarize"}]
            definition = next(
                row for row in skill["files"] if row["path"] == "skills/stock.json"
            )
            assert client.get(definition["url"]).json()["name"] == skill["display_name"]
            sources = client.get("/api/data-sources", headers=header).json()
            assert sources["total"] == 1 and sources["items"][0][
                "name"
            ] == "Stock selection-" + str(index)
            assert sources["items"][0]["visibility"] == "internal"
            source = client.get("/api/data-sources/stock", headers=header).json()
            assert source["descriptor"]["kind"] == "inventory"
            assert len(source["local_files"]) == 2
            assert (
                source["local_files"][0]["file_id"]
                == source["local_files"][1]["file_id"]
            )
            url = source["local_files"][0]["url"]
            response = client.get(url)
            assert (
                response.status_code == 200
                and response.content == b"item,count\nbox,3\n"
            )
            file_urls.append(url)
            choices = client.get(
                "/api/package-files",
                headers=header,
                params={
                    "query": "shared",
                    "prefix": "data-sources/",
                    "extensions": ".csv",
                },
            )
            assert choices.status_code == 200, choices.text
            assert [item["path"] for item in choices.json()["items"]] == [
                "data-sources/shared.csv"
            ]
            assert (
                client.get(
                    "/api/package-files",
                    headers=header,
                    params={"query": "shared", "offset": "1"},
                ).json()["items"]
                == []
            )
            for invalid_offset in ("-1", "abc", "2147483648"):
                assert (
                    client.get(
                        "/api/package-files",
                        headers=header,
                        params={"offset": invalid_offset},
                    ).status_code
                    == 400
                )
            assert choices.json()["items"][0]["url"] == url
            assert (
                choices.json()["items"][0]["sha256"]
                == hashlib.sha256(response.content).hexdigest()
            )
            assert (
                client.get(
                    "/api/package-files", headers=header, params={"query": "%"}
                ).json()["items"]
                == []
            )
            assert (
                client.get(
                    "/api/package-files", headers=header, params={"extensions": ".exe"}
                ).json()["items"]
                == []
            )
            assert (
                client.get(
                    "/api/package-files",
                    headers=header,
                    params={"extensions": "../bad"},
                ).status_code
                == 400
            )
        assert len(set(file_urls)) == 3
        client.cookies.set(auth.SESSION_COOKIE, tokens[0])
        header = {"X-Lunar-Package-Version": str(versions[1].version_id)}
        assert (
            client.get(urlsplit(file_urls[0]).path, headers=header).status_code == 404
        )
        assert client.get(file_urls[2]).status_code == 404
        assert (
            client.get(
                "/api/package-files",
                params={"package_version_id": str(versions[2].version_id)},
            ).status_code
            == 404
        )
        path = VersionStorage(tmp_path / "store").package_file(
            versions[0], "data-sources/shared.csv"
        )
        path.write_text("changed bytes")
        assert client.get(file_urls[0]).status_code == 409
        assert client.get(file_urls[1]).status_code == 200
