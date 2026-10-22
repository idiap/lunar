# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Cross-owner/version collisions, lineage constraints and confined storage."""

import asyncio
from uuid import uuid4

import asyncpg
import pytest

from domain_packages.context import (
    CURRENT_VERSION,
    PackageContext,
    VersionNotFound,
    bind_context,
    owned_context,
)
from domain_packages.repository import allocate_version, list_versions, resources
from domain_packages.storage import VersionStorage


def context():
    return PackageContext(uuid4(), uuid4(), uuid4(), 1)


def test_storage_segments_and_input_confinement(tmp_path):
    storage = VersionStorage(tmp_path)
    a, b = context(), context()
    assert storage.package_file(a, "repository/main.prism") != storage.package_file(
        b, "repository/main.prism"
    )
    assert storage.version_root(a).parts[-3:] == (
        a.user_id.hex,
        a.package_id.hex,
        a.version_id.hex,
    )
    assert storage.staging_root(a).parent == storage.version_root(a).parent
    assert storage.run_root(a, uuid4()).parent == storage.version_root(a) / "runs"
    for bad in ("../b", "/tmp/b", "repository/../../b", "repository/a\\b"):
        with pytest.raises(ValueError):
            storage.package_file(a, bad)
    with pytest.raises(ValueError):
        storage.run_file(a, uuid4(), "../foreign")


def test_storage_rejects_symlinks_at_every_level(tmp_path):
    storage = VersionStorage(tmp_path / "store")
    selected = context()
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    version = storage.version_root(selected)
    version.mkdir(parents=True)
    (version / "repository").symlink_to(foreign, target_is_directory=True)
    with pytest.raises(ValueError, match="symlinks"):
        storage.package_file(selected, "repository/input.csv")
    (version / "repository").unlink()
    version.rmdir()
    version.symlink_to(foreign, target_is_directory=True)
    with pytest.raises(ValueError, match="symlinks"):
        storage.version_root(selected)


def test_request_bindings_are_task_local_and_reset_on_failure():
    a, b = context(), context()

    async def task(selected):
        with bind_context(selected):
            await asyncio.sleep(0)
            assert CURRENT_VERSION.get() == selected
            with pytest.raises(RuntimeError):
                with bind_context(context()):
                    raise RuntimeError("stop")
            assert CURRENT_VERSION.get() == selected
        assert CURRENT_VERSION.get() is None

    async def scenario():
        await asyncio.gather(task(a), task(b))

    asyncio.run(scenario())


async def add_user(connection):
    user_id = uuid4()
    await connection.execute(
        "INSERT INTO users(id,email,password_hash) VALUES($1,$2,'disabled')",
        user_id,
        str(user_id) + "@example.invalid",
    )
    return user_id


async def version(connection, user_id, key="same"):
    return await allocate_version(
        connection,
        user_id=user_id,
        manifest={"package": {"key": key, "display_name": key}},
        archive_digest="0" * 64,
    )


async def add_rows(connection, selected):
    source_id, skill_id, run_id, report_id, output_id = (uuid4() for _ in range(5))
    owner, vid = selected.user_id, selected.version_id
    await connection.execute(
        "INSERT INTO package_workflows(id,version_id,user_id,workflow_id,registration) VALUES($1,$2,$3,'count','{}')",
        uuid4(),
        vid,
        owner,
    )
    await connection.execute(
        """INSERT INTO skills(id,user_id,version_id,skill_id,display_name,version,description,instructions,source_path,catalog_digest)
        VALUES($1,$2,$3,'same','Same','1','','Count items','skills/same.json',$4)""",
        skill_id,
        owner,
        vid,
        "sha256:" + "0" * 64,
    )
    await connection.execute(
        """INSERT INTO data_sources(id,user_id,version_id,resource_id,name,category,scope,canonical_uri,posture,
        claim_ceiling,owner,refresh_trigger,verified_as_of,schema_version,catalog_digest,descriptor)
        VALUES($1,$2,$3,'same','Same','general','package','','descriptor_only','','','','','1',$4,'{}')""",
        source_id,
        owner,
        vid,
        "sha256:" + "0" * 64,
    )
    await connection.execute(
        """INSERT INTO prism_runs(id,user_id,version_id,workflow_id,operation,mode,state,safe_input_manifest,accepted_plan_digest,artifact_root)
        VALUES($1,$2,$3,'count','run','fixture','queued','{}',$4,'unused')""",
        run_id,
        owner,
        vid,
        "sha256:" + "0" * 64,
    )
    await connection.execute(
        "INSERT INTO reports(id,user_id,version_id,logical_id,query,html) VALUES($1,$2,$3,'same','Count','Count')",
        report_id,
        owner,
        vid,
    )
    await connection.execute(
        """INSERT INTO prism_run_outputs(id,run_id,user_id,version_id,output_key,component_id,markdown,media_type,content_digest,provenance_entity_id)
        VALUES($1,$2,$3,$4,'same','count','Count','text/markdown',$5,'original:output')""",
        output_id,
        run_id,
        owner,
        vid,
        "sha256:" + "0" * 64,
    )
    return source_id, skill_id, run_id, report_id, output_id


def test_fresh_schema_allows_collisions_and_denies_foreign_selection(postgres_url):
    async def scenario():
        connection = await asyncpg.connect(postgres_url)
        try:
            first, second = await add_user(connection), await add_user(connection)
            contexts = [
                await version(connection, first),
                await version(connection, first),
                await version(connection, first, "another"),
                await version(connection, second),
            ]
            for selected in contexts:
                await add_rows(connection, selected)
            assert (
                await connection.fetchval(
                    "SELECT count(*) FROM skills WHERE skill_id='same'"
                )
                == 4
            )
            assert (
                await connection.fetchval(
                    "SELECT count(*) FROM data_sources WHERE resource_id='same'"
                )
                == 4
            )
            assert await list_versions(connection, first) == []
            await connection.execute("UPDATE package_versions SET status='ready'")
            assert len(await list_versions(connection, first)) == 3
            assert (
                await owned_context(connection, first, contexts[0].version_id)
                == contexts[0]
            )
            with pytest.raises(VersionNotFound):
                await owned_context(connection, second, contexts[0].version_id)
            with pytest.raises(asyncpg.ForeignKeyViolationError):
                await connection.execute(
                    "INSERT INTO chats(id,user_id,title,version_id) VALUES($1,$2,'Foreign',$3)",
                    uuid4(),
                    second,
                    contexts[0].version_id,
                )
        finally:
            await connection.close()

    asyncio.run(scenario())


def test_concurrent_identical_imports_allocate_new_monotonic_versions(postgres_url):
    async def scenario():
        connection = await asyncpg.connect(postgres_url)
        owner = await add_user(connection)
        await connection.close()

        async def allocate():
            c = await asyncpg.connect(postgres_url)
            try:
                return await version(c, owner)
            finally:
                await c.close()

        results = await asyncio.gather(*(allocate() for _ in range(8)))
        assert sorted(c.version for c in results) == list(range(1, 9))
        assert len({c.version_id for c in results}) == 8
        assert len({c.package_id for c in results}) == 1

    asyncio.run(scenario())


def test_composite_lineage_and_immutable_context(postgres_url):
    async def scenario():
        c = await asyncpg.connect(postgres_url)
        try:
            owner = await add_user(c)
            a, b = await version(c, owner), await version(c, owner)
            rows_a, rows_b = await add_rows(c, a), await add_rows(c, b)
            for child in ("prism_run_planned_sources", "prism_run_consumed_sources"):
                if child.endswith("planned_sources"):
                    query = f"INSERT INTO {child}(id,run_id,user_id,version_id,resource_id,required) VALUES($1,$2,$3,$4,'same',true)"
                else:
                    query = f"""INSERT INTO {child}(id,run_id,user_id,version_id,resource_id,source_local_identifier,access_mode,version_or_snapshot,safe_locator,content_digest)
                        VALUES($1,$2,$3,$4,'same','same','local','1','local',repeat('0',64))"""
                with pytest.raises(asyncpg.ForeignKeyViolationError):
                    await c.execute(query, uuid4(), rows_a[2], owner, b.version_id)
            with pytest.raises(asyncpg.ForeignKeyViolationError):
                await c.execute(
                    """INSERT INTO report_sections(id,user_id,version_id,report_id,section_id,ordinal,placeholder_name,run_output_id,rendered_markdown,content_digest,provenance_entity_id)
                    VALUES($1,$2,$3,$4,'same',0,'same',$5,'Count',repeat('0',64),'original:section')""",
                    uuid4(),
                    owner,
                    a.version_id,
                    rows_a[3],
                    rows_b[4],
                )
            with pytest.raises(asyncpg.PostgresError, match="immutable"):
                await c.execute(
                    "UPDATE reports SET version_id=$1 WHERE id=$2",
                    b.version_id,
                    rows_a[3],
                )
            chat_id = uuid4()
            await c.execute(
                "INSERT INTO chats(id,user_id,title,version_id) VALUES($1,$2,'Bound',$3)",
                chat_id,
                owner,
                a.version_id,
            )
            with pytest.raises(asyncpg.PostgresError, match="immutable"):
                await c.execute(
                    "UPDATE chats SET version_id=$1 WHERE id=$2", b.version_id, chat_id
                )
            with pytest.raises(asyncpg.PostgresError, match="immutable"):
                await c.execute(
                    "UPDATE package_versions SET version=99 WHERE id=$1", a.version_id
                )
        finally:
            await c.close()

    asyncio.run(scenario())


def test_resource_file_links_cannot_cross_context(postgres_url):
    async def scenario():
        c = await asyncpg.connect(postgres_url)
        try:
            owner = await add_user(c)
            a, b = await version(c, owner), await version(c, owner, "another")
            resource_id, file_id = uuid4(), uuid4()
            await c.execute(
                "INSERT INTO package_resources(id,user_id,version_id,collection,logical_id,document) VALUES($1,$2,$3,'skills','same','{}')",
                resource_id,
                owner,
                a.version_id,
            )
            await c.execute(
                "INSERT INTO package_files(id,user_id,version_id,path,size,sha256,media_type,storage_kind) VALUES($1,$2,$3,'skills/file.bin',0,repeat('0',64),'application/octet-stream','filesystem')",
                file_id,
                owner,
                b.version_id,
            )
            with pytest.raises(asyncpg.ForeignKeyViolationError):
                await c.execute(
                    "INSERT INTO package_resource_files(resource_id,file_id,user_id,version_id) VALUES($1,$2,$3,$4)",
                    resource_id,
                    file_id,
                    owner,
                    a.version_id,
                )
            await c.execute("UPDATE package_versions SET status='ready'")
            assert len(await resources(c, a, "skills")) == 1
            assert await resources(c, b, "skills") == []
        finally:
            await c.close()

    asyncio.run(scenario())


def test_failed_allocation_transaction_preserves_previous_versions(postgres_url):
    async def scenario():
        c = await asyncpg.connect(postgres_url)
        try:
            owner = await add_user(c)
            first = await version(c, owner)
            await c.execute(
                "UPDATE package_versions SET status='ready' WHERE id=$1",
                first.version_id,
            )
            with pytest.raises(RuntimeError):
                async with c.transaction():
                    await version(c, owner)
                    raise RuntimeError("injected commit boundary failure")
            second = await version(c, owner)
            assert second.version == 2
            assert [row["id"] for row in await list_versions(c, owner)] == [
                first.version_id
            ]
            with pytest.raises(asyncpg.PostgresError, match="immutable"):
                await c.execute(
                    "UPDATE domain_packages SET package_key='retarget' WHERE id=$1",
                    first.package_id,
                )
        finally:
            await c.close()

    asyncio.run(scenario())
