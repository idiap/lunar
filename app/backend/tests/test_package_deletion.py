# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Package deletion is owner-scoped and removes database and host artifacts."""

import asyncio
import errno
import shutil
import time
from threading import Event
from uuid import uuid4

import asyncpg
import auth
import modules.common as common
from domain_packages import routes
from domain_packages.context import PackageContext
from domain_packages.importer import import_validated, remove_version_files
from domain_packages.storage import VersionStorage
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient
from test_package_importer import staged, user


def test_file_cleanup_retries_finder_metadata_race(tmp_path, monkeypatch):
    storage = VersionStorage(tmp_path)
    context = PackageContext(uuid4(), uuid4(), uuid4(), 1)
    root = storage.version_root(context)
    runtime = root / "repository" / "runtime"
    runtime.mkdir(parents=True)
    (runtime / ".DS_Store").write_bytes(b"metadata")
    original = shutil.rmtree
    interrupted = False

    def raced_rmtree(path):
        nonlocal interrupted
        if path == root and not interrupted:
            interrupted = True
            raise OSError(errno.ENOTEMPTY, "Directory not empty", str(runtime))
        return original(path)

    monkeypatch.setattr(shutil, "rmtree", raced_rmtree)
    remove_version_files(storage, context)
    assert interrupted
    assert not root.exists()


def test_delete_owned_package_version_and_preserve_foreign_package(
    postgres_url, tmp_path, monkeypatch
):
    monkeypatch.setattr(auth, "DATABASE_URL", postgres_url)
    monkeypatch.setattr(common, "DATABASE_URL", postgres_url)
    monkeypatch.setenv("LUNAR_PACKAGE_STORAGE_ROOT", str(tmp_path / "store"))
    removed_images = []
    monkeypatch.setattr(routes, "remove_runtime_image", removed_images.append)
    deletion_started = Event()
    finish_deletion = Event()
    original_finish = routes.finish_package_deletion

    async def delayed_finish(context):
        deletion_started.set()
        await asyncio.to_thread(finish_deletion.wait)
        await original_finish(context)

    monkeypatch.setattr(routes, "finish_package_deletion", delayed_finish)

    async def setup():
        connection = await asyncpg.connect(postgres_url)
        try:
            owner, other = await user(connection), await user(connection)
            await connection.execute("UPDATE users SET email_verified_at=NOW()")
            storage = VersionStorage(tmp_path / "store")
            selected = await import_validated(
                connection, storage, user_id=owner, archive=staged(tmp_path, "owned")
            )
            prepared = await import_validated(
                connection, storage, user_id=owner, archive=staged(tmp_path, "prepared")
            )
            await connection.execute(
                "UPDATE package_versions SET runtime_state='ready', runtime_image='fixture-image' WHERE id=$1",
                prepared.version_id,
            )
            foreign = await import_validated(
                connection, storage, user_id=other, archive=staged(tmp_path, "foreign")
            )
            await connection.execute(
                "INSERT INTO chats(id,user_id,title,version_id) VALUES(gen_random_uuid(),$1,'Bound',$2)",
                owner,
                selected.version_id,
            )
            return selected, prepared, foreign, await auth.create_session(owner)
        finally:
            await connection.close()

    selected, prepared, foreign, token = asyncio.run(setup())
    app = Starlette(
        routes=[
            Route(
                "/api/packages/versions/{version_id}",
                routes.delete_package_version,
                methods=["DELETE"],
            ),
            Route("/api/packages/versions", routes.package_versions),
        ]
    )
    with TestClient(app) as client:
        client.cookies.set(auth.SESSION_COOKIE, token)
        assert (
            client.delete(f"/api/packages/versions/{foreign.version_id}").status_code
            == 404
        )
        response = client.delete(f"/api/packages/versions/{selected.version_id}")
        assert response.status_code == 202
        assert response.json()["success"] is True
        assert deletion_started.wait(5)
        listed = client.get("/api/packages/versions").json()["versions"]
        assert next(item for item in listed if item["id"] == str(selected.version_id))[
            "deletion_started_at"
        ]
        assert (
            client.delete(f"/api/packages/versions/{selected.version_id}").status_code
            == 409
        )
        finish_deletion.set()
        deadline = time.monotonic() + 5
        while any(
            item["id"] == str(selected.version_id)
            for item in client.get("/api/packages/versions").json()["versions"]
        ):
            assert time.monotonic() < deadline
            time.sleep(0.05)
        assert removed_images == []
        assert (
            client.delete(f"/api/packages/versions/{prepared.version_id}").status_code
            == 202
        )
        deadline = time.monotonic() + 5
        while any(
            item["id"] == str(prepared.version_id)
            for item in client.get("/api/packages/versions").json()["versions"]
        ):
            assert time.monotonic() < deadline
            time.sleep(0.05)
        assert removed_images == [prepared.version_id]
        assert (
            client.delete(f"/api/packages/versions/{selected.version_id}").status_code
            == 404
        )

    async def verify():
        connection = await asyncpg.connect(postgres_url)
        try:
            assert not await connection.fetchval(
                "SELECT EXISTS(SELECT 1 FROM package_versions WHERE id=$1)",
                selected.version_id,
            )
            assert not await connection.fetchval(
                "SELECT EXISTS(SELECT 1 FROM package_versions WHERE id=$1)",
                prepared.version_id,
            )
            assert await connection.fetchval(
                "SELECT EXISTS(SELECT 1 FROM package_versions WHERE id=$1)",
                foreign.version_id,
            )
            assert not await connection.fetchval(
                "SELECT EXISTS(SELECT 1 FROM chats WHERE version_id=$1)",
                selected.version_id,
            )
        finally:
            await connection.close()

    asyncio.run(verify())
    storage = VersionStorage(tmp_path / "store")
    assert not storage.version_root(selected).exists()
    assert not storage.version_root(prepared).exists()
    assert storage.version_root(foreign).exists()
