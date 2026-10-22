# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Planner and stdio entrypoints bind only owned package contexts."""

import asyncio
from uuid import uuid4
import asyncpg
import pytest
import planner
import server
import modules.common as common
from domain_packages.context import CURRENT_VERSION, bind_context, VersionNotFound
from domain_packages.importer import import_validated
from domain_packages.storage import VersionStorage
from lunar_planner.config import current_config
from lunar_planner.ports import current_ports
from test_package_importer import user, staged


def test_planner_scope_is_owned_and_retained_across_awaits(
    postgres_url, tmp_path, monkeypatch
):
    monkeypatch.setattr(common, "DATABASE_URL", postgres_url)
    monkeypatch.setenv("LUNAR_PACKAGE_STORAGE_ROOT", str(tmp_path / "store"))

    async def setup():
        connection = await asyncpg.connect(postgres_url)
        try:
            owner = await user(connection)
            return [
                await import_validated(
                    connection,
                    VersionStorage(tmp_path / "store"),
                    user_id=owner,
                    archive=staged(tmp_path, str(index)),
                )
                for index in range(2)
            ]
        finally:
            await connection.close()

    contexts = asyncio.run(setup())

    async def inspect(request, **kwargs):
        expected = CURRENT_VERSION.get()
        assert expected is not None
        identity = tuple(
            str(value)
            for value in (expected.user_id, expected.package_id, expected.version_id)
        )
        surface = current_ports().surface
        assert surface is not None
        await asyncio.sleep(0.01)
        assert current_config().context_identity == identity
        assert surface.snapshot()["context_identity"] == list(identity)
        assert (
            surface.snapshot()["reports"][0]["content"]
            == "![Stock](plot.svg)\nThree boxes."
        )
        return {"version_id": str(expected.version_id)}

    monkeypatch.setattr(planner, "_run_pipeline", inspect)

    async def scenario():
        async def invoke(context):
            with bind_context(context):
                return await planner.run_pipeline(
                    {"command_text": "Inspect"},
                    principal=str(context.user_id),
                    channel="http",
                )

        results = await asyncio.gather(*(invoke(context) for context in contexts))
        assert [row["version_id"] for row in results] == [
            str(context.version_id) for context in contexts
        ]
        assert current_config().context_identity is None
        with bind_context(contexts[0]):
            rejected = await planner.run_pipeline(
                {"command_text": "Inspect"}, principal=str(uuid4()), channel="http"
            )
            assert rejected["status"] == "failed"
        with bind_context(None):
            absent = await planner.run_pipeline(
                {"command_text": "Inspect"}, channel="stdio"
            )
            assert (
                absent["status"] == "blocked"
                and absent["execution_status"] == "not_started"
            )
        assert CURRENT_VERSION.get() is None

    asyncio.run(scenario())
    monkeypatch.delenv("LUNAR_STDIO_USER_ID", raising=False)
    monkeypatch.delenv("LUNAR_STDIO_VERSION_ID", raising=False)
    with pytest.raises(ValueError, match="stdio requires"):
        asyncio.run(server.stdio_context())
    monkeypatch.setenv("LUNAR_STDIO_USER_ID", str(contexts[0].user_id))
    monkeypatch.setenv("LUNAR_STDIO_VERSION_ID", str(contexts[0].version_id))
    assert asyncio.run(server.stdio_context()) == contexts[0]
    monkeypatch.setenv("LUNAR_STDIO_USER_ID", str(uuid4()))
    with pytest.raises(VersionNotFound):
        asyncio.run(server.stdio_context())
