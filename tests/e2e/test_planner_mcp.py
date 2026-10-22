# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Real MCP automatic planning through frozen quality gates and package workers."""

import asyncio
import json
import asyncpg
import auth
import modules.common as common
import reports
import pytest
from starlette.testclient import TestClient
from domain_packages.importer import import_validated
from domain_packages.worker.preparation import prepare_runtime
import test_package_workers as fixtures

pytestmark = pytest.mark.e2e


def test_mcp_automatic_release_planning_only_and_owned_continuations(
    e2e_database_url, tmp_path, worker_image, monkeypatch
):
    for module in (auth, common, reports):
        monkeypatch.setattr(module, "DATABASE_URL", e2e_database_url)
    monkeypatch.setenv("LUNAR_PACKAGE_STORAGE_ROOT", str(tmp_path / "store"))
    from control_plane.quality_runtime import configure_quality_runtime

    configure_quality_runtime("local")

    async def setup():
        connection = await asyncpg.connect(e2e_database_url)
        try:
            first, storage, _ = await fixtures.imported(
                connection, tmp_path, "mcp-first", "", planning_hooks=False
            )
            second = await import_validated(
                connection,
                storage,
                user_id=first.user_id,
                archive=fixtures.archive(
                    tmp_path, "mcp-second", "", planning_hooks=False
                ),
            )
            await connection.execute("UPDATE users SET email_verified_at=NOW()")
            for context in (first, second):
                await prepare_runtime(
                    connection, context, storage, base_image=worker_image
                )
            return first, second, await auth.create_session(first.user_id)
        finally:
            await connection.close()

    first, second, session = asyncio.run(setup())
    import importlib
    import server

    server = importlib.reload(server)
    with TestClient(server.app, base_url="http://localhost:8080") as client:
        client.cookies.set(auth.SESSION_COOKIE, session)
        base = {
            "Authorization": "Bearer " + auth.mcp_token_for_user(str(first.user_id)),
            "Accept": "application/json, text/event-stream",
            "X-Lunar-Package-Version": str(first.version_id),
        }
        initialized = client.post(
            "/mcp",
            headers=base,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "lunar-e0", "version": "1"},
                },
            },
        )
        assert initialized.status_code == 200, initialized.text
        base["MCP-Protocol-Version"] = initialized.json()["result"]["protocolVersion"]

        def call(arguments, version=None):
            header = {
                **base,
                "X-Lunar-Package-Version": str(version or first.version_id),
            }
            response = client.post(
                "/mcp",
                headers=header,
                json={
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {"name": "planner", "arguments": arguments},
                },
            )
            assert response.status_code == 200, response.text
            result = response.json()["result"]
            assert not result.get("isError"), result
            return result.get("structuredContent") or json.loads(
                result["content"][0]["text"]
            )

        arguments = {
            "command_text": "Create an inventory workflow that increments count 41 and reports the result.",
            "references": ["workflow:inventory"],
            "desired_inputs": ["count"],
            "desired_outputs": ["count"],
            "supplied_inputs": {"count": 41},
        }
        header = {"X-Lunar-Package-Version": str(first.version_id)}
        initial = client.get("/api/prism/runs", headers=header).json()["total"]
        plan = call(
            {
                **arguments,
                "command_text": "Plan only: create an inventory workflow that increments count 41 and reports the result.",
            }
        )
        assert plan["status"] == "planning_only", plan
        assert plan["execution_status"] == "not_started" and plan["report"] is None
        assert client.get("/api/prism/runs", headers=header).json()["total"] == initial
        completed = call(arguments)
        assert completed["status"] == "completed", completed
        assert (
            completed["execution_status"] == "completed"
            and completed["publication"] == "published"
        )
        assert completed["released_artifact"]["structured_value"] == {"count": 42}
        stages = [row["source"]["stage"] for row in completed["reasoning"]["entries"]]
        assert stages.count("quality_review") == 2
        assert all(
            stage in stages
            for stage in ("execution", "delivery_evaluation", "publication")
        )
        report = client.get(completed["report"]["url"])
        assert report.status_code == 200 and "42" in report.text
        wrong = {"X-Lunar-Package-Version": str(second.version_id)}
        assert (
            client.get(
                "/api/report/" + completed["report"]["report_id"], headers=wrong
            ).status_code
            == 404
        )
        missing = call(
            {key: value for key, value in arguments.items() if key != "supplied_inputs"}
        )
        assert (
            missing["status"] == "clarification_required" and missing["continuation_id"]
        ), missing
        rejected = call(
            {
                "command_text": "The count is 41.",
                "supplied_inputs": {"count": 41},
                "continuation_id": missing["continuation_id"],
            },
            second.version_id,
        )
        assert (
            rejected["status"] == "failed"
            and rejected["execution_status"] == "not_started"
        ), rejected
        resumed = call(
            {
                "command_text": "The count is 41.",
                "supplied_inputs": {"count": 41},
                "continuation_id": missing["continuation_id"],
            }
        )
        assert resumed["status"] == "completed", resumed
        assert resumed["released_artifact"]["structured_value"] == {"count": 42}

        before_failure = len(client.get("/api/report", headers=header).json())
        failed = call(
            {**arguments, "supplied_inputs": {"count": 41, "action": "symlink"}}
        )
        assert failed["status"] == "failed" and failed["report"] is None, failed
        assert len(client.get("/api/report", headers=header).json()) == before_failure

    # Use the actual retained stdio transport with explicit local ownership.
    async def stdio():
        import os
        import sys
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        environment = {
            **os.environ,
            "DATABASE_URL": e2e_database_url,
            "LUNAR_STDIO_USER_ID": str(first.user_id),
            "LUNAR_STDIO_VERSION_ID": str(first.version_id),
            "LUNAR_PACKAGE_STORAGE_ROOT": str(tmp_path / "store"),
            "LUNAR_PROFILE": "local",
        }
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["app/backend/server.py", "--transport", "stdio"],
            env=environment,
        )
        async with stdio_client(parameters) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                response = await session.call_tool("planner", arguments)
                assert not response.isError, response
                result = response.structuredContent or json.loads(
                    response.content[0].text
                )
                assert (
                    result["status"] == "completed"
                    and result["publication"] == "unavailable"
                ), result
                assert result["report"] is None and result["released_artifact"][
                    "structured_value"
                ] == {"count": 42}

    asyncio.run(asyncio.wait_for(stdio(), 45))
