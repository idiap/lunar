# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Real PostgreSQL/filesystem import, collision and publication recovery checks."""

import asyncio
import json
from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest

from domain_packages.archive import validate_archive
from domain_packages.context import VersionNotFound, owned_context
from domain_packages.importer import import_validated, reconcile_imports
from domain_packages.repository import list_versions, resources
from domain_packages.storage import VersionStorage
from test_package_archive import write_zip


async def user(connection):
    identity = uuid4()
    await connection.execute(
        "INSERT INTO users(id,email,password_hash) VALUES($1,$2,'disabled')",
        identity,
        str(identity) + "@example.invalid",
    )
    return identity


def staged(tmp_path, label):
    path = tmp_path / (label + ".zip")
    write_zip(path)
    return validate_archive(path, tmp_path / (label + "-validated"))


def test_import_projects_complete_owned_records_and_exact_bytes(postgres_url, tmp_path):
    async def scenario():
        connection = await asyncpg.connect(postgres_url)
        try:
            owner = await user(connection)
            other = await user(connection)
            archive = staged(tmp_path, "first")
            storage = VersionStorage(tmp_path / "store")
            context = await import_validated(
                connection, storage, user_id=owner, archive=archive
            )
            assert await owned_context(connection, owner, context.version_id) == context
            with pytest.raises(VersionNotFound):
                await owned_context(connection, other, context.version_id)
            assert not await list_versions(connection, other)
            for kind, docs in archive.documents.items():
                actual = await resources(connection, context, kind)
                assert {
                    row["logical_id"]: json.loads(row["document"]) for row in actual
                } == {row["id"]: row for row in docs}
            rows = await connection.fetch(
                "SELECT * FROM package_files WHERE version_id=$1", context.version_id
            )
            assert len(rows) == len(archive.manifest["files"])
            original_root = (
                Path(__file__).resolve().parents[3]
                / "tests/domain_packages/fixtures/domain-package-v1/neutral-complete"
            )
            for row in rows:
                stored = storage.package_file(context, row["path"])
                expected = (original_root / row["path"]).read_bytes()
                if row["storage_kind"] == "database":
                    assert row["payload"] == expected and not stored.exists()
                else:
                    assert stored.read_bytes() == expected and row["payload"] is None
            report = await connection.fetchrow(
                "SELECT * FROM reports WHERE version_id=$1", context.version_id
            )
            assert report["imported"] and report["version"] == 2
            assert (
                await connection.fetchval(
                    "SELECT content FROM report_revisions WHERE report_id=$1",
                    report["id"],
                )
                == "Two boxes."
            )
            assert (
                await connection.fetchval(
                    "SELECT COUNT(*) FROM report_sections WHERE report_id=$1",
                    report["id"],
                )
                == 1
            )
            assert await connection.fetchval(
                "SELECT imported FROM prism_runs WHERE version_id=$1",
                context.version_id,
            )
            assert await connection.fetchval("SELECT COUNT(*) FROM templates") == 0
            assert (
                await connection.fetchval(
                    "SELECT COUNT(*) FROM package_import_mappings WHERE version_id=$1",
                    context.version_id,
                )
                == sum(map(len, archive.documents.values())) + 2
            )
            assert not storage.staging_root(context).exists()
        finally:
            await connection.close()

    asyncio.run(scenario())


def test_repeat_imports_and_users_have_independent_navigation_and_bytes(
    postgres_url, tmp_path
):
    async def scenario():
        connection = await asyncpg.connect(postgres_url)
        try:
            owners = [await user(connection), await user(connection)]
            storage = VersionStorage(tmp_path / "store")
            contexts = []
            for index, owner in enumerate([owners[0], owners[0], owners[1]]):
                contexts.append(
                    await import_validated(
                        connection,
                        storage,
                        user_id=owner,
                        archive=staged(tmp_path, str(index)),
                    )
                )
            assert [row.version for row in contexts] == [1, 2, 1]
            assert (
                contexts[0].package_id
                == contexts[1].package_id
                != contexts[2].package_id
            )
            assert len({storage.version_root(row) for row in contexts}) == 3
            ids = [
                await connection.fetchval(
                    "SELECT id FROM reports WHERE version_id=$1", row.version_id
                )
                for row in contexts
            ]
            assert len(set(ids)) == 3
            assert len(await list_versions(connection, owners[0])) == 2
            assert len(await list_versions(connection, owners[1])) == 1
        finally:
            await connection.close()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "stage",
    [
        "allocated",
        "staged",
        "records_inserted",
        "before_publication",
        "after_publication",
        "before_commit",
        "after_commit",
    ],
)
def test_failure_boundaries_never_expose_partial_versions(
    postgres_url, tmp_path, stage
):
    async def scenario():
        connection = await asyncpg.connect(postgres_url)
        try:
            owner = await user(connection)
            storage = VersionStorage(tmp_path / "store")
            previous = await import_validated(
                connection, storage, user_id=owner, archive=staged(tmp_path, "previous")
            )
            captured = None

            async def fail(current, context):
                nonlocal captured
                captured = context
                if current == stage:
                    raise RuntimeError("injected failure")

            with pytest.raises(RuntimeError, match="injected"):
                await import_validated(
                    connection,
                    storage,
                    user_id=owner,
                    archive=staged(tmp_path, "failed"),
                    checkpoint=fail,
                )
            assert captured is not None
            ready = await list_versions(connection, owner)
            expected = 2 if stage == "after_commit" else 1
            assert len(ready) == expected
            assert storage.version_root(previous).exists()
            status = await connection.fetchval(
                "SELECT status FROM package_versions WHERE id=$1", captured.version_id
            )
            assert status == ("ready" if stage == "after_commit" else "failed")
            count = await connection.fetchval(
                "SELECT COUNT(*) FROM package_resources WHERE version_id=$1",
                captured.version_id,
            )
            assert bool(count) == (stage == "after_commit")
            assert storage.version_root(captured).exists() == (stage == "after_commit")
            assert not storage.staging_root(captured).exists()
        finally:
            await connection.close()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "stage",
    ["allocated", "staged", "after_publication", "before_commit", "after_commit"],
)
def test_interrupted_import_is_reconciled_without_touching_ready_versions(
    postgres_url, tmp_path, stage
):
    class ProcessStopped(BaseException):
        pass

    async def scenario():
        connection = await asyncpg.connect(postgres_url)
        try:
            owner = await user(connection)
            storage = VersionStorage(tmp_path / "store")
            captured = None

            async def stop(current, context):
                nonlocal captured
                captured = context
                if current == stage:
                    raise ProcessStopped()

            with pytest.raises(ProcessStopped):
                await import_validated(
                    connection,
                    storage,
                    user_id=owner,
                    archive=staged(tmp_path, "interrupted"),
                    checkpoint=stop,
                )
            assert captured is not None
            recovered = await reconcile_imports(connection, storage)
            assert recovered == (
                [] if stage == "after_commit" else [captured.version_id]
            )
            assert not storage.staging_root(captured).exists()
            assert storage.version_root(captured).exists() == (stage == "after_commit")
            assert await reconcile_imports(connection, storage) == []
        finally:
            await connection.close()

    asyncio.run(scenario())


def test_reconciliation_cannot_remove_an_active_import(postgres_url, tmp_path):
    async def scenario():
        connection = await asyncpg.connect(postgres_url)
        recovery = await asyncpg.connect(postgres_url)
        try:
            owner = await user(connection)
            storage = VersionStorage(tmp_path / "store")

            async def verify(current, context):
                if current == "after_publication":
                    assert await reconcile_imports(recovery, storage) == []
                    assert storage.version_root(context).exists()
                    assert not await list_versions(recovery, owner)

            await import_validated(
                connection,
                storage,
                user_id=owner,
                archive=staged(tmp_path, "active"),
                checkpoint=verify,
            )
            assert len(await list_versions(connection, owner)) == 1
        finally:
            await connection.close()
            await recovery.close()

    asyncio.run(scenario())


def test_simultaneous_imports_allocate_distinct_versions(postgres_url, tmp_path):
    async def scenario():
        connection = await asyncpg.connect(postgres_url)
        owner = await user(connection)
        await connection.close()
        storage = VersionStorage(tmp_path / "store")
        archives = [staged(tmp_path, str(index)) for index in range(4)]

        async def upload(archive):
            connection = await asyncpg.connect(postgres_url)
            try:
                return await import_validated(
                    connection, storage, user_id=owner, archive=archive
                )
            finally:
                await connection.close()

        contexts = await asyncio.gather(*(upload(archive) for archive in archives))
        assert sorted(row.version for row in contexts) == [1, 2, 3, 4]
        assert all(storage.version_root(row).exists() for row in contexts)

    asyncio.run(scenario())
