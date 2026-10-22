# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Server and route-only contracts transferred from BioAgents B2."""

import asyncio
import json
import server
from lunar_planner.entrypoint import run_planner_request


def test_route_only_planning_has_no_execution_authority():
    result = run_planner_request(
        "design a new inventory workflow", execution_mode="route_only"
    )
    assert result["mode"] == "new_workflow"
    assert result["route_only"] is True
    assert result["execution_allowed"] is False
    assert result["performed_actions"] == []


def test_server_registers_only_the_canonical_compact_tool():
    assert "Use `planner`" in server.mcp.instructions
    assert "exact released" in server.mcp.instructions
    tools = asyncio.run(server.mcp.list_tools())
    assert {tool.name for tool in tools} == {"planner"}
    description = " ".join(tools[0].description.split())
    assert "Automatically plan" in description
    assert "exact released artifact" in description


def test_server_check_reports_readiness(capsys):
    server.main(["--check", "--profile", "local"])
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "service": "lunar",
        "status": "ready",
        "tool_count": 1,
        "tool_names": ["planner"],
        "quality_runtime": {
            "profile": "local",
            "status": "configured",
            "adapter_id": "lunar-local-deterministic-evaluator",
            "server_owned": True,
            "required_for_material_scientific_release": True,
        },
    }


def test_server_parser_accepts_service_transport():
    args = server.build_parser().parse_args(
        [
            "--transport",
            "streamable-http",
            "--host",
            "0.0.0.0",
            "--port",
            "9000",
            "--path",
            "/lunar/mcp",
            "--profile",
            "local",
        ]
    )
    assert (args.transport, args.host, args.port, args.path, args.profile) == (
        "streamable-http",
        "0.0.0.0",
        9000,
        "/lunar/mcp",
        "local",
    )
