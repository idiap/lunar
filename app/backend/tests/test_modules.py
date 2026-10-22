# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import asyncio
import importlib
import json
from types import SimpleNamespace
from typing import Any, cast

import pytest
from ag_ui.core import RunAgentInput
from ag_ui.encoder import EventEncoder
from pydantic import ValidationError

from modules.ai_models import decrypt_api_key, encrypt_api_key
from modules.ai_models import _model_json
from modules.chat import (
    DEFAULT_PLANNER_TOOLS,
    _chat_events,
    _completion_arguments,
    _litellm_messages,
    _model_tool_result_content,
    _planning_only_boundary_requested,
    _tool_result_content,
    chat_configuration,
    fallback_chat_title,
    tool_descriptor,
)
from modules.prompts import substitute_variables
from modules.schemas import AIModelInput, PromptInput, ReportInput, TemplateInput


def test_variable_substitution_and_escaped_braces() -> None:
    assert (
        substitute_variables("Study {cohort}; JSON {{ok}}", {"cohort": "HER2+"})
        == "Study HER2+; JSON {ok}"
    )


def test_explicit_planning_only_request_does_not_force_execution_lifecycle() -> None:
    messages = [
        {"role": "user", "content": "Only plan this workflow; do not execute it."}
    ]

    assert _planning_only_boundary_requested(messages) is True
    assert (
        _planning_only_boundary_requested(
            [{"role": "user", "content": "Review this proposed workflow."}]
        )
        is True
    )
    assert (
        _planning_only_boundary_requested(
            [{"role": "user", "content": "Review this plan and execute it."}]
        )
        is False
    )


def test_variable_substitution_reports_all_missing_values() -> None:
    with pytest.raises(ValueError, match="cohort, endpoint"):
        substitute_variables("{endpoint}: {cohort}")


def test_ai_model_key_round_trip() -> None:
    encrypted = encrypt_api_key("secret-key")
    assert encrypted != "secret-key"
    assert decrypt_api_key(encrypted) == "secret-key"


def test_ai_model_json_config_is_a_dictionary() -> None:
    assert _model_json({"config": "{}"})["config"] == {}


def test_module_inputs_match_icebrook_contracts() -> None:
    assert PromptInput(name="Prompt").content is None
    assert TemplateInput(name="Template", content="# Body").agent is None
    assert ReportInput(name="Report", content="# Body").content_type_id is None
    assert (
        AIModelInput(
            name="GPT", provider="openai", model_id="gpt-4.1", api_key="key"
        ).config
        == {}
    )


def test_app_registers_module_routes() -> None:
    application = importlib.import_module("server").app
    route_paths = {route.path for route in application.routes}
    assert {
        "/api/prompts",
        "/api/prompts/run",
        "/api/report",
        "/api/templates",
        "/api/ai-models",
        "/api/chat",
        "/api/chat/tools",
        "/api/chats",
        "/api/chats/{chat_id}",
        "/api/data-sources",
        "/api/data-sources/{resource_id}",
        "/api/prism/workflows",
        "/api/prism/workflows/{workflow_id}/runs",
        "/api/prism/runs",
        "/api/prism/runs/{run_id}",
        "/api/prism/runs/{run_id}/provenance",
        "/api/templates/{template_id}/outputs",
        "/api/templates/{template_id}/runs",
        "/api/report/{report_id}/provenance",
        "/api/report/{report_id}/sections/{section_id}/provenance",
    } <= route_paths
    assert any(
        route.path == "/api/chats/{chat_id}" and "DELETE" in route.methods
        for route in application.routes
    )
    assert any(
        route.path == "/api/prism/runs/{run_id}" and "DELETE" in route.methods
        for route in application.routes
    )


def test_chat_configuration_requires_model_and_filters_tools() -> None:
    default = chat_configuration({"aiModelId": "303ffca7-2e8b-4ed2-a1d6-2ca006df68dc"})
    assert default.enabled_tools == list(DEFAULT_PLANNER_TOOLS)
    assert default.chat_id is None

    configured = chat_configuration(
        {
            "aiModelId": "303ffca7-2e8b-4ed2-a1d6-2ca006df68dc",
            "enabledTools": ["planner", "planner"],
        }
    )
    assert str(configured.ai_model_id) == "303ffca7-2e8b-4ed2-a1d6-2ca006df68dc"
    assert configured.enabled_tools == ["planner"]

    with pytest.raises(ValidationError):
        chat_configuration({"enabledTools": ["planner"]})


def test_chat_title_fallback_is_brief() -> None:
    assert fallback_chat_title(
        "Design a reusable longitudinal ctDNA monitoring workflow"
    ) == ("Design a reusable longitudinal ctDNA monitoring")
    assert fallback_chat_title("!!!") == "New chat"


def test_only_planner_is_enabled_by_default() -> None:
    assert DEFAULT_PLANNER_TOOLS == ("planner",)
    assert tool_descriptor({"name": "planner"})["default_enabled"] is True
    assert tool_descriptor({"name": "plan_request"})["default_enabled"] is False
    assert (
        chat_configuration(
            {"aiModelId": "303ffca7-2e8b-4ed2-a1d6-2ca006df68dc", "enabledTools": []}
        ).enabled_tools
        == []
    )


def test_chat_accepts_database_json_model_config() -> None:
    arguments = _completion_arguments(
        {
            "provider": "openai",
            "model_id": "gpt-4.1",
            "api_base": None,
            "api_version": None,
            "encrypted_api_key": encrypt_api_key("secret-key"),
            "config": '{"temperature": 0.2}',
        },
        [{"role": "user", "content": "Hello"}],
        [],
    )
    assert arguments["temperature"] == 0.2


def test_chat_compacts_planner_results_for_the_model_but_preserves_full_output() -> (
    None
):
    payload = {
        "schema_version": "lunar.planner.routing-decision/v1",
        "status": "needs_quality_review",
        "primary_intent": "external_data_query",
        "blockers": ["quality_planning_required"],
        "planner_result_id": "planner-result-1",
        "continuation_id": "continuation-1",
        "quality_plan_id": "quality-plan-1",
        "plan": {
            "disposition": "quality_planning_required",
            "digest": "sha256:planner",
            "large_internal_plan": "x" * 100_000,
        },
    }
    wrapped = {"structuredContent": {"result": payload}}

    full = _tool_result_content(wrapped)
    compact = _model_tool_result_content("planner", wrapped)
    compact_payload = json.loads(compact)

    assert len(full) > 100_000
    assert len(compact) < 2_000
    assert compact_payload["continuation_id"] == "continuation-1"
    assert compact_payload["quality_plan_id"] == "quality-plan-1"
    assert "large_internal_plan" not in compact


def test_saved_tool_history_is_compacted_before_the_next_model_call() -> None:
    payload = {
        "planner_result_id": "planner-result-1",
        "continuation_id": "continuation-1",
        "quality_plan_id": "quality-plan-1",
        "plan": {
            "disposition": "quality_planning_required",
            "large_internal_plan": "x" * 100_000,
        },
    }
    tool_call = SimpleNamespace(
        id="call-1",
        function=SimpleNamespace(name="planner", arguments="{}"),
    )
    messages = [
        SimpleNamespace(
            role="assistant",
            content=None,
            name=None,
            tool_calls=[tool_call],
        ),
        SimpleNamespace(
            role="tool",
            content=json.dumps({"structuredContent": {"result": payload}}),
            name=None,
            tool_call_id="call-1",
            tool_calls=None,
        ),
    ]

    converted = _litellm_messages(messages)

    assert len(converted[1]["content"]) < 2_000
    assert json.loads(converted[1]["content"])["continuation_id"] == "continuation-1"


def test_released_structure_evidence_retains_nested_confidence_regions() -> None:
    compact = _model_tool_result_content(
        "planner",
        {
            "schema_version": "mcp.evaluated-delivery/v1",
            "candidate_withheld": False,
            "released_artifact": {
                "records": [
                    {
                        "native_payload": {
                            "plddt_summary": {
                                "mean": 72.0,
                                "low_confidence_regions": [[501, 580]],
                            }
                        }
                    }
                ]
            },
        },
    )

    assert "72.0" in compact
    assert "501" in compact and "580" in compact


def test_ag_ui_chat_runs_an_enabled_mcp_tool(monkeypatch) -> None:
    class Stream:
        def __init__(self, chunks):
            self.chunks = chunks

        def __aiter__(self):
            return self._iterate()

        async def _iterate(self):
            for chunk in self.chunks:
                yield chunk

    responses = iter(
        [
            Stream(
                [
                    {
                        "choices": [
                            {
                                "delta": {
                                    "tool_calls": [
                                        {
                                            "index": 0,
                                            "id": "call-1",
                                            "function": {
                                                "name": "planner",
                                                "arguments": '{"command_text":"Plan it"}',
                                            },
                                        }
                                    ]
                                }
                            }
                        ]
                    }
                ]
            ),
            Stream([{"choices": [{"delta": {"content": "Plan ready."}}]}]),
        ]
    )

    completion_calls = []

    async def completion(**kwargs):
        completion_calls.append(kwargs)
        return next(responses)

    import litellm

    monkeypatch.setattr(litellm, "acompletion", completion)

    class FakeMCP:
        calls = []

        async def call_tool(self, name, arguments):
            self.calls.append((name, arguments))
            return {"status": "planned"}

    fake_mcp = FakeMCP()
    import planner

    async def pipeline(arguments, **kwargs):
        return await fake_mcp.call_tool("planner", arguments)

    monkeypatch.setattr(planner, "run_pipeline", pipeline)
    body = RunAgentInput.model_validate(
        {
            "threadId": "thread-1",
            "runId": "run-1",
            "state": {},
            "messages": [{"id": "user-1", "role": "user", "content": "Plan it"}],
            "tools": [],
            "context": [],
            "forwardedProps": {},
        }
    )
    model = {
        "id": "00000000-0000-0000-0000-000000000001",
        "provider": "openai",
        "model_id": "gpt-4.1",
        "api_base": None,
        "api_version": None,
        "encrypted_api_key": encrypt_api_key("secret-key"),
        "config": {},
    }
    enabled = {
        "planner": {
            "name": "planner",
            "description": "Plan work",
            "inputSchema": {"type": "object"},
        }
    }
    saved_messages = []

    async def persist(messages):
        saved_messages[:] = messages
        return {"id": "chat-1", "title": "Plan it"}

    async def collect():
        return [
            event
            async for event in _chat_events(
                body,
                model,
                enabled,
                cast(Any, fake_mcp),
                EventEncoder(),
                persist_messages=persist,
            )
        ]

    encoded = asyncio.run(collect())
    events = [json.loads(event.removeprefix("data: ").strip()) for event in encoded]
    assert completion_calls[0]["messages"][0]["role"] == "system"
    assert "continuation_id" in completion_calls[0]["messages"][0]["content"]
    assert (
        "Preserve explicit planning-only requests"
        in completion_calls[0]["messages"][0]["content"]
    )
    assert all("tool_choice" not in call for call in completion_calls)
    assert fake_mcp.calls == [
        (
            "planner",
            {
                "command_text": "Plan it",
                "ai_model_id": "00000000-0000-0000-0000-000000000001",
            },
        )
    ]
    assert [event["type"] for event in events] == [
        "RUN_STARTED",
        "TEXT_MESSAGE_START",
        "TEXT_MESSAGE_END",
        "TOOL_CALL_START",
        "TOOL_CALL_ARGS",
        "TOOL_CALL_END",
        "TOOL_CALL_RESULT",
        "TEXT_MESSAGE_START",
        "TEXT_MESSAGE_CONTENT",
        "TEXT_MESSAGE_END",
        "CUSTOM",
        "RUN_FINISHED",
    ]
    assert events[6]["content"] == '{"status": "planned"}'
    assert events[8]["delta"] == "Plan ready."
    assert events[10] == {
        "type": "CUSTOM",
        "name": "chat_saved",
        "value": {"id": "chat-1", "title": "Plan it"},
    }
    assert [message["role"] for message in saved_messages] == [
        "user",
        "assistant",
        "tool",
        "assistant",
    ]
    assert saved_messages[1]["toolCalls"][0]["function"]["name"] == "planner"


def test_chat_streams_worker_observations_before_completion_and_saves_them(monkeypatch):
    import threading
    import planner

    # Resource binding has separate PostgreSQL coverage; retain this streaming oracle.
    monkeypatch.setattr(planner, "run_pipeline", planner._run_pipeline)
    import litellm
    from control_plane.quality_runtime import configure_quality_runtime

    configure_quality_runtime("local")
    entered, release = threading.Event(), threading.Event()

    def plan(**kwargs):
        entered.set()
        assert release.wait(5)
        return {
            "planner_receipt": {"disposition": "blocked"},
            "blockers": ["Missing source"],
        }

    monkeypatch.setattr(planner, "_plan_request", plan)
    responses = iter(
        [
            [
                {
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "id": "call-live",
                                        "function": {
                                            "name": "planner",
                                            "arguments": '{"command_text":"Run work"}',
                                        },
                                    }
                                ]
                            }
                        }
                    ]
                }
            ],
            [{"choices": [{"delta": {"content": "Missing source."}}]}],
        ]
    )

    async def completion(**kwargs):
        chunks = next(responses)

        async def stream():
            for chunk in chunks:
                yield chunk

        return stream()

    monkeypatch.setattr(litellm, "acompletion", completion)
    saved = []

    async def persist(messages):
        saved[:] = messages
        return {"id": "chat"}

    body = RunAgentInput.model_validate(
        {
            "threadId": "t",
            "runId": "r",
            "state": {},
            "messages": [{"id": "u", "role": "user", "content": "Run work"}],
            "tools": [],
            "context": [],
            "forwardedProps": {},
        }
    )
    model = {
        "id": "00000000-0000-0000-0000-000000000001",
        "provider": "openai",
        "model_id": "test",
        "api_base": None,
        "api_version": None,
        "encrypted_api_key": encrypt_api_key("test"),
        "config": {},
    }

    async def scenario():
        events = []
        try:
            async for raw in _chat_events(
                body,
                model,
                {"planner": {"name": "planner"}},
                cast(Any, None),
                EventEncoder(),
                persist_messages=persist,
                principal="user",
            ):
                event = json.loads(raw.removeprefix("data: ").strip())
                events.append(event)
                if event.get("name") == "planner_reasoning" and not release.is_set():
                    assert event["value"]["tool_call_id"] == "call-live"
                    assert not any(row["type"] == "TOOL_CALL_RESULT" for row in events)
                    assert await asyncio.to_thread(entered.wait, 2)
                    release.set()
        finally:
            release.set()
        return events

    events = asyncio.run(scenario())
    results = [row for row in events if row["type"] == "TOOL_CALL_RESULT"]
    assert len(results) == 1, events
    payload = json.loads(results[0]["content"])
    assert payload["status"] == "blocked"
    assert payload["reasoning"]["entries"]
    assert all(
        row["presentation"]["status"] != "pending"
        for row in payload["reasoning"]["entries"]
    )
    assert (
        json.loads(next(row["content"] for row in saved if row["role"] == "tool"))
        == payload
    )
    assert not any(row.get("outcome") for row in events)


def test_retired_pending_history_is_readable_without_execution_resume():
    body = RunAgentInput.model_validate(
        {
            "threadId": "old",
            "runId": "next",
            "state": {},
            "messages": [
                {
                    "id": "a",
                    "role": "assistant",
                    "toolCalls": [
                        {
                            "id": "old-call",
                            "type": "function",
                            "function": {"name": "execute_plan", "arguments": "{}"},
                        }
                    ],
                },
                {"id": "u", "role": "user", "content": "Explain the limitations."},
            ],
            "tools": [],
            "context": [],
            "forwardedProps": {},
        }
    )
    messages = _litellm_messages(body.messages)
    assert messages[1]["tool_call_id"] == "old-call"
    assert json.loads(messages[1]["content"])["execution_performed"] is False
    assert messages[2]["role"] == "user"
