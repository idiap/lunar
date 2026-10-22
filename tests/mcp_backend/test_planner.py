# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Tests for Planner.

This module protects expected behavior for the corresponding workflow, script, or repository surface. Key concepts: regression coverage, interface stability, and output integrity.
"""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "app" / "backend" / "planner.py"


def _load_planner_module():
    """Load planner module."""
    spec = importlib.util.spec_from_file_location("report_backend_planner", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_plan_request_uses_route_only_planner_boundary(monkeypatch) -> None:
    """Verify plan request uses route only planner boundary."""
    module = _load_planner_module()
    captured: dict[str, object] = {}

    def fake_run(command_text: str, **kwargs):
        """Fake run."""
        captured.update(command_text=command_text, **kwargs)
        return {"schema_version": "lunar.planner.routing-decision/v1"}

    import lunar_planner.entrypoint as entrypoint

    monkeypatch.setattr(entrypoint, "run_planner_request", fake_run)
    continuation = {"schema_version": "lunar.planner.continuation/v1"}
    continuation_id = module.STATE.put("continuation", continuation)
    result = module._plan_request(
        "design an inventory workflow",
        references=["prior-report.html"],
        desired_outputs=["controlled report"],
        supplied_inputs={"warehouse": "main"},
        continuation_id=continuation_id,
    )

    assert result["schema_version"] == "lunar.planner.routing-decision/v1"
    assert "repo_root" not in captured
    assert captured["execution_mode"] == "route_only"
    from domain_packages.context import CURRENT_VERSION

    assert captured["authority_envelope"] == {
        "principal": str(CURRENT_VERSION.get().user_id),
        "mode": "planning_only",
        "execution": "forbidden",
        "external_actions": "forbidden",
        "mutation": "forbidden",
    }
    assert captured["continuation"] == continuation
    assert result["planner_result_id"].startswith("planner_result-")


def test_register_planner_tool_uses_canonical_name() -> None:
    """Verify register planner tool uses canonical name."""
    module = _load_planner_module()

    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("test")
    module.register_planner_tool(mcp)
    assert [tool.name for tool in asyncio.run(mcp.list_tools())] == ["planner"]


def test_backend_registers_planner_tool(monkeypatch) -> None:
    """Verify backend registers planner tool."""
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://localhost:8080")
    monkeypatch.setenv("AUTH_SECRET", "test-secret")
    monkeypatch.syspath_prepend(str(ROOT / "app" / "backend"))
    app_path = ROOT / "app" / "backend" / "app.py"
    spec = importlib.util.spec_from_file_location("report_backend_app", app_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    tools = asyncio.run(module.mcp.list_tools())
    tool_names = {tool.name for tool in tools}

    assert module.mcp.name == "lunar"
    assert tool_names == {"planner"}
    assert all(not name.startswith("bioagents") for name in tool_names)
    planner_tool = next(tool for tool in tools if tool.name == "planner")
    properties = planner_tool.inputSchema["properties"]
    assert properties["command_text"]["minLength"] == 1
    assert (
        "natural-language request for this turn"
        in properties["command_text"]["description"]
    )
    assert "missing_fields" in properties["supplied_inputs"]["description"]
    assert "opaque continuation_id" in properties["continuation_id"]["description"]
    assert set(properties) == {
        "ai_model_id",
        "command_text",
        "references",
        "desired_inputs",
        "desired_outputs",
        "supplied_inputs",
        "continuation_id",
    }
    assert planner_tool.inputSchema["additionalProperties"] is False
