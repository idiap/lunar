# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Planner selections are built from authenticated imported PostgreSQL records."""

import asyncio
import hashlib
from dataclasses import replace
from uuid import uuid4

import asyncpg
import pytest

from domain_packages.archive import validate_archive
from domain_packages.context import VersionNotFound
from domain_packages.importer import import_validated
from domain_packages.planning import planner_binding, PlanningUnavailable
from domain_packages.storage import VersionStorage
from lunar_planner import run_planner_request
from lunar_planner.config import bind_planner, current_config
from lunar_planner.ports import current_ports
from test_package_importer import user, staged
from test_package_archive import write_zip


def test_imported_planning_isolated_across_owners_and_versions(postgres_url, tmp_path):
    async def scenario():
        connection = await asyncpg.connect(postgres_url)
        try:
            owners = [await user(connection), await user(connection)]
            storage = VersionStorage(tmp_path / "store")
            contexts = []
            bindings = []
            for index, owner in enumerate([owners[0], owners[0], owners[1]]):
                archive = staged(tmp_path, str(index))
                context = await import_validated(
                    connection, storage, user_id=owner, archive=archive
                )
                contexts.append(context)
                bindings.append(await planner_binding(connection, context, storage))

            async def plan(index):
                config, ports = bindings[index]
                with bind_planner(config, ports):
                    await asyncio.sleep(0)
                    surface = current_ports().surface
                    assert surface is not None
                    snapshot = surface.snapshot()
                    assert snapshot["context_identity"] == list(config.context_identity)
                    assert current_config() == config
                    assert [row["id"] for row in snapshot["skills"]] == ["skill:stock"]
                    assert len(snapshot["reports"]) == 1
                    assert len(snapshot["data_sources"]) == 1
                    snapshot["skills"].clear()
                    assert len(surface.snapshot()["skills"]) == 1
                    result = run_planner_request("Use stock to summarize item counts")
                    assert result["executed"] is False
                    assert not config.state_root.exists()
                    return config.context_identity

            identities = await asyncio.gather(*(plan(index) for index in range(3)))
            assert len(set(identities)) == 3
            for forged in [
                replace(contexts[0], user_id=owners[1]),
                replace(contexts[0], package_id=uuid4()),
                replace(contexts[0], version=2),
            ]:
                with pytest.raises(VersionNotFound):
                    await planner_binding(connection, forged, storage)
        finally:
            await connection.close()

    asyncio.run(scenario())


def test_declared_policy_requires_explicit_worker_provider(postgres_url, tmp_path):
    async def scenario():
        connection = await asyncpg.connect(postgres_url)
        try:
            owner = await user(connection)
            storage = VersionStorage(tmp_path / "store")

            def with_policy(manifest, payloads):
                content = b"def plan(request): return {}\n"
                path = "repository/policy.py"
                manifest["files"].append(
                    {
                        "path": path,
                        "size": len(content),
                        "media_type": "text/x-python",
                        "sha256": hashlib.sha256(content).hexdigest(),
                    }
                )
                manifest["collections"]["repository"][0]["files"].append(path)
                manifest["runtime"]["entrypoints"].append(
                    {
                        "id": "policy",
                        "operation": "plan",
                        "file": path,
                        "callable": "plan",
                    }
                )
                manifest["runtime"]["planning_hooks"] = ["policy"]
                return manifest, [*payloads, (path, content)]

            archive_path = tmp_path / "policy.zip"
            write_zip(archive_path, mutate=with_policy)
            archive = validate_archive(archive_path, tmp_path / "policy-stage")
            assert archive.manifest["runtime"]["planning_hooks"]
            context = await import_validated(
                connection, storage, user_id=owner, archive=archive
            )
            with pytest.raises(PlanningUnavailable, match="policy worker"):
                await planner_binding(connection, context, storage)

            class WorkerPort:
                def evaluate(self, operation, inputs):
                    return None

            provider = WorkerPort()
            _, ports = await planner_binding(
                connection, context, storage, policy_provider=provider
            )
            assert ports.domain_policy is provider
        finally:
            await connection.close()

    asyncio.run(scenario())
