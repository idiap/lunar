# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Real PostgreSQL/file export snapshots, owner isolation and repeatable import."""

import asyncio
from typed_report_fixtures import typed_client as typed_client
import hashlib
import json

import asyncpg
import auth
import modules.common as common
import pytest
import sys
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient
from domain_packages.archive import validate_archive
from domain_packages.export_routes import export_package
from domain_packages.exporter import VersionSnapshot
from domain_packages.files import package_file
from domain_packages.importer import import_validated
from domain_packages.middleware import PackageSelectionMiddleware
from domain_packages.storage import VersionStorage
from modules.reports import get_report, update_report, create_report, delete_report
from test_package_archive import write_zip
from test_package_importer import staged, user


def application():
    app = Starlette(
        routes=[
            Route("/api/report", create_report, methods=["POST"]),
            Route("/api/report/{report_id}", delete_report, methods=["DELETE"]),
            Route("/api/packages/versions/{version_id}/export", export_package),
            Route("/api/report/{report_id}", get_report),
            Route("/api/report/{report_id}", update_report, methods=["PUT"]),
            Route("/api/package-files/{file_id}", package_file),
        ]
    )
    app.add_middleware(PackageSelectionMiddleware)
    return app


def test_export_roundtrip_retains_bytes_edits_history_and_ownership(
    postgres_url, tmp_path, monkeypatch
):
    for module in (auth, common):
        monkeypatch.setattr(module, "DATABASE_URL", postgres_url)
    storage = VersionStorage(tmp_path / "store")
    monkeypatch.setenv("LUNAR_PACKAGE_STORAGE_ROOT", str(storage.root))
    original = staged(tmp_path, "initial")
    original_files = {
        item["path"]: (original.root / item["path"]).read_bytes()
        for item in original.manifest["files"]
    }
    original_report = original.documents["reports"][0]

    async def setup():
        connection = await asyncpg.connect(postgres_url)
        try:
            owners = [await user(connection), await user(connection)]
            await connection.execute("UPDATE users SET email_verified_at=NOW()")
            first = await import_validated(
                connection, storage, user_id=owners[0], archive=original
            )
            second = await import_validated(
                connection,
                storage,
                user_id=owners[0],
                archive=staged(tmp_path, "second"),
            )
            foreign = await import_validated(
                connection,
                storage,
                user_id=owners[1],
                archive=staged(tmp_path, "foreign"),
            )
            report = await connection.fetchval(
                "SELECT id FROM reports WHERE version_id=$1", first.version_id
            )
            return first, second, foreign, report, await auth.create_session(owners[0])
        finally:
            await connection.close()

    first, second, foreign, report, token = asyncio.run(setup())
    with TestClient(application()) as client:
        endpoint = "/api/packages/versions/" + str(first.version_id) + "/export"
        assert client.get(endpoint).status_code == 401
        client.cookies.set(auth.SESSION_COOKIE, token)
        assert (
            client.get(
                "/api/packages/versions/" + str(foreign.version_id) + "/export"
            ).status_code
            == 404
        )
        assert (
            client.get(endpoint + "?user_id=" + str(foreign.user_id)).status_code == 400
        )
        header = {"X-Lunar-Package-Version": str(first.version_id)}
        response = client.put(
            "/api/report/" + str(report),
            headers=header,
            json={"content": original_report["content"] + " Updated."},
        )
        assert response.status_code == 200, response.text
        response = client.get(endpoint)
        assert response.status_code == 200, response.text
        assert response.headers["content-type"] == "application/zip"
        assert (
            response.headers["etag"]
            == '"' + hashlib.sha256(response.content).hexdigest() + '"'
        )
        path = tmp_path / "export.zip"
        path.write_bytes(response.content)
        archive = validate_archive(path, tmp_path / "roundtrip")
        exported = archive.documents["reports"][0]
        assert (
            exported["content"] == original_report["content"] + " Updated."
            and exported["version"] == 3
        )
        assert [(row["version"], row["content"]) for row in exported["revisions"]] == [
            (1, "Two boxes."),
            (2, original_report["content"]),
        ]
        for key in (
            "attachments",
            "sections",
            "runs",
            "outputs",
            "provenance",
            "template_snapshot",
        ):
            assert exported[key] == original_report[key], key
        assert (
            exported["metadata"]["lunar_export_snapshot"]["import_archive_digest"]
            == original.archive_digest
        )
        for name, data in original_files.items():
            if name != "reports/stock.json":
                assert (archive.root / name).read_bytes() == data
        assert not list((storage.root / ".uploads").glob("upload-*"))

        async def reimport():
            connection = await asyncpg.connect(postgres_url)
            try:
                receipts = await connection.fetch("SELECT * FROM package_exports")
                assert (
                    len(receipts) == 1 and receipts[0]["version_id"] == first.version_id
                )
                third = await import_validated(
                    connection, storage, user_id=foreign.user_id, archive=archive
                )
                new_report = await connection.fetchval(
                    "SELECT id FROM reports WHERE version_id=$1", third.version_id
                )
                assert new_report != report
                return third, new_report, await auth.create_session(foreign.user_id)
            finally:
                await connection.close()

        third, new_report, other_token = asyncio.run(reimport())
        client.cookies.set(auth.SESSION_COOKIE, other_token)
        value = client.get(
            "/api/report/" + str(new_report),
            headers={"X-Lunar-Package-Version": str(third.version_id)},
        )
        assert value.status_code == 200, value.text
        assert (
            value.json()["content"] == exported["content"]
            and value.json()["version"] == 3
        )
        assert (
            client.get(value.json()["attachments"][0]["url"]).content
            == original_files["reports/plot.svg"]
        )
        # A second export does not invent duplicate reports or lose original facts.
        again = client.get(
            "/api/packages/versions/" + str(third.version_id) + "/export"
        )
        assert again.status_code == 200, again.text
        path = tmp_path / "again.zip"
        path.write_bytes(again.content)
        checked = validate_archive(path, tmp_path / "again")
        assert len(checked.documents["reports"]) == 1
        for key in (
            "content",
            "revisions",
            "attachments",
            "sections",
            "runs",
            "outputs",
            "provenance",
        ):
            assert checked.documents["reports"][0][key] == exported[key]


def test_export_snapshot_excludes_later_edits_and_rejects_changed_files(
    postgres_url, tmp_path, monkeypatch
):
    for module in (auth, common):
        monkeypatch.setattr(module, "DATABASE_URL", postgres_url)
    storage = VersionStorage(tmp_path / "store")
    monkeypatch.setenv("LUNAR_PACKAGE_STORAGE_ROOT", str(storage.root))

    async def setup():
        connection = await asyncpg.connect(postgres_url)
        try:
            owner = await user(connection)
            await connection.execute("UPDATE users SET email_verified_at=NOW()")
            context = await import_validated(
                connection, storage, user_id=owner, archive=staged(tmp_path, "snapshot")
            )
            return context, await auth.create_session(owner)
        finally:
            await connection.close()

    context, token = asyncio.run(setup())
    original_collect = VersionSnapshot.collect

    async def concurrent_edit(self, manifest):
        await original_collect(self, manifest)
        writer = await asyncpg.connect(postgres_url)
        try:
            await writer.execute(
                "UPDATE reports SET name='Later edit' WHERE user_id=$1", context.user_id
            )
        finally:
            await writer.close()

    monkeypatch.setattr(VersionSnapshot, "collect", concurrent_edit)
    with TestClient(application()) as client:
        client.cookies.set(auth.SESSION_COOKIE, token)
        endpoint = "/api/packages/versions/" + str(context.version_id) + "/export"
        response = client.get(endpoint)
        assert response.status_code == 200, response.text
        path = tmp_path / "snapshot.zip"
        path.write_bytes(response.content)
        archive = validate_archive(path, tmp_path / "snapshot-read")
        assert archive.documents["reports"][0]["name"] == "Stock report"

        async def changed_after_copy(self, manifest):
            await original_collect(self, manifest)
            storage.package_file(context, "reports/plot.svg").write_bytes(
                b"changed after snapshot"
            )

        monkeypatch.setattr(VersionSnapshot, "collect", changed_after_copy)
        assert client.get(endpoint).status_code == 409
        monkeypatch.setattr(VersionSnapshot, "collect", original_collect)
        storage.package_file(context, "reports/plot.svg").write_bytes(b"corrupted")
        response = client.get(endpoint)
        assert response.status_code == 409, response.text
        assert not list((storage.root / ".uploads").glob("upload-*"))

        async def count():
            connection = await asyncpg.connect(postgres_url)
            try:
                return await connection.fetchval("SELECT COUNT(*) FROM package_exports")
            finally:
                await connection.close()

        assert asyncio.run(count()) == 1


@pytest.mark.parametrize("generation_type", ["template", "prism"])
def test_template_import_keeps_generated_report_immutable(
    postgres_url, tmp_path, monkeypatch, generation_type
):
    for module in (auth, common):
        monkeypatch.setattr(module, "DATABASE_URL", postgres_url)
    storage = VersionStorage(tmp_path / "store")
    monkeypatch.setenv("LUNAR_PACKAGE_STORAGE_ROOT", str(storage.root))

    def mutate(manifest, payloads):
        values = dict(payloads)
        document = json.loads(values["reports/stock.json"])
        document["metadata"]["generation_type"] = generation_type
        values["reports/stock.json"] = json.dumps(document).encode()
        for row in manifest["files"]:
            row.update(
                size=len(values[row["path"]]),
                sha256=hashlib.sha256(values[row["path"]]).hexdigest(),
            )
        return manifest, list(values.items())

    path = tmp_path / "template.zip"
    write_zip(path, mutate=mutate)

    async def setup():
        connection = await asyncpg.connect(postgres_url)
        try:
            owner = await user(connection)
            await connection.execute("UPDATE users SET email_verified_at=NOW()")
            context = await import_validated(
                connection,
                storage,
                user_id=owner,
                archive=validate_archive(path, tmp_path / "validated"),
            )
            identity = await connection.fetchval(
                "SELECT id FROM reports WHERE version_id=$1", context.version_id
            )
            return context, identity, await auth.create_session(owner)
        finally:
            await connection.close()

    context, identity, token = asyncio.run(setup())
    with TestClient(application()) as client:
        client.cookies.set(auth.SESSION_COOKIE, token)
        headers = {"X-Lunar-Package-Version": str(context.version_id)}
        assert (
            client.get("/api/report/" + str(identity), headers=headers).json()[
                "read_only"
            ]
            is True
        )
        assert (
            client.put(
                "/api/report/" + str(identity),
                headers=headers,
                json={"content": "changed"},
            ).status_code
            == 409
        )
        response = client.get(
            "/api/packages/versions/" + str(context.version_id) + "/export"
        )
        assert response.status_code == 200, response.text
        path = tmp_path / "exported.zip"
        path.write_bytes(response.content)
        archive = validate_archive(path, tmp_path / "reexported")
        assert (
            archive.documents["reports"][0]["metadata"]["generation_type"]
            == generation_type
        )


def test_current_manual_reports_resolve_package_links_and_omit_deleted_content(
    postgres_url, tmp_path, monkeypatch
):
    for module in (auth, common):
        monkeypatch.setattr(module, "DATABASE_URL", postgres_url)
    storage = VersionStorage(tmp_path / "store")
    monkeypatch.setenv("LUNAR_PACKAGE_STORAGE_ROOT", str(storage.root))

    async def setup():
        connection = await asyncpg.connect(postgres_url)
        try:
            owner = await user(connection)
            other = await user(connection)
            await connection.execute("UPDATE users SET email_verified_at=NOW()")
            context = await import_validated(
                connection, storage, user_id=owner, archive=staged(tmp_path, "manual")
            )
            foreign = await import_validated(
                connection, storage, user_id=other, archive=staged(tmp_path, "other")
            )
            files = [
                await connection.fetchval(
                    "SELECT id FROM package_files WHERE version_id=$1 AND path='reports/plot.svg'",
                    item.version_id,
                )
                for item in (context, foreign)
            ]
            return context, files, await auth.create_session(owner)
        finally:
            await connection.close()

    context, files, token = asyncio.run(setup())
    with TestClient(application()) as client:
        client.cookies.set(auth.SESSION_COOKIE, token)
        headers = {"X-Lunar-Package-Version": str(context.version_id)}
        link = (
            "/api/package-files/"
            + str(files[0])
            + "?package_version_id="
            + str(context.version_id)
        )
        created = client.post(
            "/api/report",
            headers=headers,
            json={"name": "New report", "content": "![Plot](" + link + ")"},
        )
        assert created.status_code == 201, created.text
        deleted = client.post(
            "/api/report",
            headers=headers,
            json={"name": "Deleted report", "content": "Must not travel"},
        ).json()
        assert (
            client.delete("/api/report/" + deleted["id"], headers=headers).status_code
            == 200
        )
        response = client.get(
            "/api/packages/versions/" + str(context.version_id) + "/export"
        )
        assert response.status_code == 200, response.text
        path = tmp_path / "manual-export.zip"
        path.write_bytes(response.content)
        archive = validate_archive(path, tmp_path / "manual-exported")
        assert len(archive.documents["reports"]) == 2
        document = next(
            row for row in archive.documents["reports"] if row["name"] == "New report"
        )
        assert document["attachments"] == [{"link": link, "file": "reports/plot.svg"}]
        assert not any(
            row["name"] == "Deleted report" for row in archive.documents["reports"]
        )
        foreign = "/api/package-files/" + str(files[1])
        assert (
            client.put(
                "/api/report/" + created.json()["id"],
                headers=headers,
                json={"content": "![Foreign](" + foreign + ")"},
            ).status_code
            == 200
        )
        assert (
            client.get(
                "/api/packages/versions/" + str(context.version_id) + "/export"
            ).status_code
            == 409
        )


def test_empty_version_exports_as_empty_collections(
    postgres_url, tmp_path, monkeypatch
):
    for module in (auth, common):
        monkeypatch.setattr(module, "DATABASE_URL", postgres_url)
    storage = VersionStorage(tmp_path / "store")
    monkeypatch.setenv("LUNAR_PACKAGE_STORAGE_ROOT", str(storage.root))
    path = tmp_path / "empty.zip"

    def compatible(manifest, payloads):
        manifest["runtime"][
            "python"
        ] = f"=={sys.version_info.major}.{sys.version_info.minor}.*"
        return manifest, payloads

    write_zip(path, "empty", mutate=compatible)

    async def setup():
        connection = await asyncpg.connect(postgres_url)
        try:
            owner = await user(connection)
            await connection.execute("UPDATE users SET email_verified_at=NOW()")
            context = await import_validated(
                connection,
                storage,
                user_id=owner,
                archive=validate_archive(path, tmp_path / "empty-validated"),
            )
            return context, await auth.create_session(owner)
        finally:
            await connection.close()

    context, token = asyncio.run(setup())
    with TestClient(application()) as client:
        client.cookies.set(auth.SESSION_COOKIE, token)
        result = client.get(
            "/api/packages/versions/" + str(context.version_id) + "/export"
        )
        assert result.status_code == 200, result.text
        target = tmp_path / "empty-export.zip"
        target.write_bytes(result.content)
        archive = validate_archive(target, tmp_path / "empty-exported")
        assert all(not items for items in archive.manifest["collections"].values())
        assert archive.manifest["files"] == []
        assert (
            result.headers["x-lunar-export-id"]
            and result.headers["x-lunar-snapshot-at"]
        )


def test_typed_export_reimport_preserves_original_contract(
    typed_client, postgres_url, tmp_path
):
    client, contexts, ids, documents, storage = typed_client
    for i in (0, 1):
        response = client.get(
            "/api/packages/versions/" + str(contexts[i].version_id) + "/export"
        )
        assert response.status_code == 200, response.text
        path = tmp_path / f"typed-export-{i}.zip"
        path.write_bytes(response.content)
        archive = validate_archive(path, tmp_path / f"typed-export-{i}")
        exported = archive.documents["reports"][0]
        assert (
            exported["metadata"]["typed_report"]
            == documents[i]["metadata"]["typed_report"]
        )
        assert exported["template_snapshot"] == documents[i]["template_snapshot"]

        async def reimport():
            connection = await asyncpg.connect(postgres_url)
            try:
                context = await import_validated(
                    connection, storage, user_id=contexts[0].user_id, archive=archive
                )
                identity = await connection.fetchval(
                    "SELECT id FROM reports WHERE version_id=$1", context.version_id
                )
                return context, str(identity)
            finally:
                await connection.close()

        context, identity = asyncio.run(reimport())
        response = client.get(
            "/api/report/" + identity,
            headers={"X-Lunar-Package-Version": str(context.version_id)},
        )
        assert response.status_code == 200, response.text
        assert (
            response.json()["typed_report"] == documents[i]["metadata"]["typed_report"]
        )
        assert client.get(response.json()["attachments"][0]["url"]).status_code == 200
