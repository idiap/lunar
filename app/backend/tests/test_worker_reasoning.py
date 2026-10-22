# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Recorded model text and reasoning occurrences survive worker projection."""

import asyncio
import hashlib
import json
import uuid

import pytest
from prism.language.core import CoreType
from prism.runtime import EffectRequest
from prism.runtime.results import TraceEvent, OccurrenceOutcome
from domain_packages.worker.prism import (
    ObservedHandler,
    ObservedRecorder,
    ObservedTrace,
    _provider_arguments,
    run_with_reasoning,
)
from domain_packages.worker import observations
from prism_runs.reasoning import PublicSource, source_digest


def test_provider_schema_name_is_normalized_for_azure_openai_limits():
    name = (
        "Isabelle Physics/Derivation Trace Preformalization Expansion Support Artifact"
    )
    configured, unwrap_scalar = _provider_arguments(
        {
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": name,
                    "strict": True,
                    "schema": {"type": "object", "properties": {}},
                },
            }
        }
    )
    provider_name = configured["response_format"]["json_schema"]["name"]
    assert (
        provider_name
        == "Isabelle_Physics_Derivation_Trace_Preformalization_Expansion_Sup"
    )
    assert len(provider_name) == 64
    assert unwrap_scalar is False


@pytest.mark.parametrize(
    "answer,status", [('"Answer <42>"', "accepted"), ("invalid JSON", "rejected")]
)
def test_model_messages_and_answer_survive_projection(monkeypatch, answer, status):
    events, calls, details = [], [], {}

    def completion(**arguments):
        calls.append(arguments)
        return {
            "choices": [
                {"message": {"content": answer, "reasoning_content": "private"}}
            ]
        }

    handler = ObservedHandler(
        model="openai/gpt-5.6-sol",
        completion=completion,
        callback=lambda **event: events.append(event),
        model_calls=details,
    )
    request = EffectRequest(
        "call:1",
        "generate",
        ("Question <x>\n" + "long " * 1000,),
        {},
        CoreType("String"),
        ("AI.Generate",),
        metadata={"output_schema": {"type": "string"}},
    )
    result = handler.execute(request)
    ObservedRecorder(None, lambda **event: events.append(event), details).record(
        request, result
    )
    assert len(events) == 2
    assert events[-1]["status"] == status
    assert events[0]["model_call"]["input_text"] == "\n\n".join(
        f"{message['role']}:\n{message['content']}" for message in calls[0]["messages"]
    )
    assert "output_text" not in events[0]["model_call"]
    assert events[-1]["model_call"]["output_text"] == answer
    assert not details

    projected = []

    async def insert(connection, **kwargs):
        projected.append(kwargs)
        return kwargs

    monkeypatch.setattr(observations, "insert_entry", insert)

    async def project():
        for sequence, payload in enumerate(events):
            await observations.project_event(
                None,
                None,
                uuid.uuid4(),
                {"kind": "reasoning", "sequence": sequence, "payload": payload},
            )

    asyncio.run(project())
    assert projected[0]["source_event_key"] == "model:call:1:running"
    assert projected[1]["source_event_key"] == "model:call:1:result"
    source = PublicSource.model_validate_json(projected[1]["source"].model_dump_json())
    assert source.model_call is not None
    assert source.model_call.model_id == "openai/gpt-5.6-sol"
    assert source.model_call.output_text == answer
    assert "reasoning_content" not in source.model_dump_json()


def test_reasoning_steps_preserve_order_repetition_and_outcomes():
    from dataclasses import replace

    events = []
    trace = ObservedTrace(lambda **event: events.append(event))
    for execution in ("completed", "failed", "running"):
        node = TraceEvent(
            "workflow-node",
            "assess",
            metadata={"component": "steps.Assess", "workflow_id": "RefineWorkflow"},
            outcome=OccurrenceOutcome(),
        )
        trace.append(node)
        assert events[-1]["status"] == "running"
        if execution != "running":
            trace[-1] = replace(node, outcome=OccurrenceOutcome(execution=execution))
            if execution == "completed":
                assert events[-1]["status"] == "running"
                trace[-1] = replace(
                    node,
                    outcome=OccurrenceOutcome(
                        execution="completed", contract="satisfied"
                    ),
                )
    trace.finish()
    assert [event["status"] for event in events] == [
        "running",
        "completed",
        "running",
        "failed",
        "running",
        "interrupted",
    ]
    assert len({event["source_event_key"].rsplit(":", 1)[0] for event in events}) == 3
    assert events[0]["reasoning_step"] == {
        "name": "assess",
        "component": "steps.Assess",
        "workflow": "RefineWorkflow",
    }


def test_real_runtime_emits_start_before_completion_and_preserves_trace():
    from prism.language import parse_source, check, elaborate, compile
    from prism.runtime import EffectRecorder, FakeEffectHandler

    program = compile(elaborate(check(parse_source("""
def increment(count: Int) -> Int:
    return count + 1

workflow calculate(count: Int) -> Int:
    [incremented: increment(count)]
    return incremented

def main(count: Int) -> Int:
    return solve calculate(count)
"""))))
    events = []
    output = run_with_reasoning(
        program,
        handler=FakeEffectHandler(),
        effect_recorder=EffectRecorder(),
        entry_arguments={"count": 1},
        callback=lambda **event: events.append(event),
    )
    assert output.status == "accepted"
    assert [event["status"] for event in events] == ["running", "completed"]
    assert [event["reasoning_step"]["name"] for event in events] == ["incremented"] * 2
    assert type(output.trace) is list
    assert output.to_dict()["trace"]


def test_legacy_source_digest_is_unchanged():
    original = dict(
        stage="Model call",
        status="running",
        summary="Model call started.",
        rationale_summary="No source-provided rationale is available.",
        limitations=[],
        evidence_references=[],
    )
    digest = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(
                original, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            ).encode()
        ).hexdigest()
    )
    assert source_digest(PublicSource.model_validate(original)) == digest


@pytest.mark.parametrize("fail", [False, True])
def test_direct_hook_model_calls_record_text_and_failures(fail):
    from domain_packages.worker.prism import observed_completion

    events = []

    def completion(**arguments):
        if fail:
            raise RuntimeError("provider failed")
        return {"choices": [{"message": {"content": "answer"}}]}

    call = observed_completion(
        completion, "openai/gpt-5.6-sol", lambda **event: events.append(event)
    )
    arguments = {"messages": [{"role": "user", "content": "question"}]}
    if fail:
        with pytest.raises(RuntimeError):
            call(**arguments)
    else:
        assert call(**arguments)["choices"][0]["message"]["content"] == "answer"
    assert events[0]["model_call"] == {
        "model_id": "openai/gpt-5.6-sol",
        "input_text": "user:\nquestion",
    }
    assert events[-1]["status"] == ("failed" if fail else "completed")
    assert events[-1]["model_call"].get("output_text") == (None if fail else "answer")
    assert (
        events[0]["source_event_key"].rsplit(":", 1)[0]
        == events[1]["source_event_key"].rsplit(":", 1)[0]
    )
