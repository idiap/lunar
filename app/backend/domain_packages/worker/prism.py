# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Host-owned Prism compiler/runtime used inside the isolated package worker."""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from prism.language.core import Ok, GeneratedValue, RecordValue
from pathlib import Path
from typing import Any, Callable, Mapping

from prism.adapters.litellm import LiteLLMEffectHandler
from prism.language import (
    check as check_program,
    compile as compile_program,
    elaborate,
    parse_source,
)
from prism.runtime import CompositeEffectHandler, EffectRecorder, FileArtifactStore, run
from prism.sdk import WorkspaceModuleLoader


@dataclass(frozen=True)
class PrismExecutionResult:
    status: str
    typed_result: Any
    trace: tuple[Any, ...]
    effect_records: Mapping[str, Any]
    source_hash: str
    module_hashes: Mapping[str, str]
    diagnostics: tuple[str, ...]
    effect_recorder: EffectRecorder = field(repr=False, compare=False)
    run_output: Any = field(default=None, repr=False, compare=False)


class PrismExecutionError(RuntimeError):
    def __init__(
        self,
        phase: str,
        message: str,
        *,
        effect_records: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(f"PRISM {phase} failed: {message}")
        self.phase = phase
        self.effect_records = dict(effect_records or {})


def _safe_error(error: Exception, api_key: str) -> str:
    message = str(error)
    return message.replace(api_key, "[redacted]") if api_key else message


def _sha256(value: str) -> str:
    return value if value.startswith("sha256:") else f"sha256:{value}"


def _provider_arguments(arguments: Mapping[str, Any]) -> tuple[dict[str, Any], bool]:
    """Normalize structured-output metadata for OpenAI-compatible providers."""
    configured = dict(arguments)
    response_format = configured.get("response_format")
    if not isinstance(response_format, Mapping):
        return configured, False
    json_schema = response_format.get("json_schema")
    if not isinstance(json_schema, Mapping):
        return configured, False
    provider_json_schema = dict(json_schema)
    name = provider_json_schema.get("name")
    if isinstance(name, str):
        normalized = re.sub(r"[^A-Za-z0-9_-]", "_", name)
        provider_json_schema["name"] = (normalized or "prism_generated_output")[:64]
    schema = json_schema.get("schema")
    unwrap_scalar = isinstance(schema, Mapping) and schema.get("type") != "object"
    if isinstance(schema, Mapping) and schema.get("type") != "object":
        provider_json_schema["schema"] = {
            "type": "object",
            "properties": {"value": {str(key): value for key, value in schema.items()}},
            "required": ["value"],
            "additionalProperties": False,
        }
    provider_response_format = dict(response_format)
    provider_response_format["json_schema"] = provider_json_schema
    configured["response_format"] = provider_response_format
    return configured, unwrap_scalar


def _unwrap_provider_scalar(response: Any) -> dict[str, Any]:
    choices = (
        response.get("choices") if isinstance(response, Mapping) else response.choices
    )
    if not choices:
        raise RuntimeError("model returned no choices")
    choice = choices[0]
    message = choice.get("message") if isinstance(choice, Mapping) else choice.message
    if isinstance(message, Mapping):
        parsed = message.get("parsed")
        content = message.get("content")
    else:
        parsed = getattr(message, "parsed", None)
        content = getattr(message, "content", None)

    envelope = parsed
    if envelope is None and isinstance(content, Mapping):
        envelope = content
    if envelope is None and isinstance(content, str):
        try:
            envelope = json.loads(content)
        except ValueError as exc:
            raise RuntimeError("model returned invalid structured JSON") from exc
    if not isinstance(envelope, Mapping) or "value" not in envelope:
        raise RuntimeError("model returned no scalar output envelope")
    return {"choices": [{"message": {"content": json.dumps(envelope["value"])}}]}


def _completion_callable(
    selected_model: Any,
    completion: Callable[..., Any] | None,
) -> Callable[..., Any]:
    def call(**arguments: Any) -> Any:
        provider_completion = completion
        if provider_completion is None:
            raise RuntimeError("model access requires a scoped host channel")

        configuration = dict(selected_model.config)
        for controlled in (
            "api_base",
            "api_key",
            "api_version",
            "messages",
            "model",
            "response_format",
        ):
            configuration.pop(controlled, None)
        configuration.update(arguments)
        configuration, unwrap_scalar = _provider_arguments(configuration)
        configuration["api_key"] = selected_model.api_key
        if selected_model.api_base:
            configuration["api_base"] = selected_model.api_base
        if selected_model.api_version:
            configuration["api_version"] = selected_model.api_version
        try:
            response = provider_completion(**configuration)
            return _unwrap_provider_scalar(response) if unwrap_scalar else response
        except Exception as exc:
            raise RuntimeError(_safe_error(exc, selected_model.api_key)) from None

    return call


def execute_prism(
    *,
    source: Path,
    entry_argument: str,
    prepared_input: Mapping[str, Any],
    selected_model: Any,
    artifact_root: Path,
    completion: Callable[..., Any] | None = None,
    on_reasoning: Callable[..., None] | None = None,
    effect_handler: Any = None,
) -> PrismExecutionResult:
    """Parse, check, compile, and execute one registered public entrypoint."""
    source = source.resolve(strict=True)
    source.relative_to(Path("/package"))
    project = source.parent
    if not source.is_file() or source.suffix != ".prism":
        raise PrismExecutionError(
            "resolve", "registered Prism entrypoint is unavailable"
        )
    if prepared_input["entry_argument_name"] != entry_argument:
        raise PrismExecutionError("input", "prepared entry argument name is invalid")

    try:
        parsed = parse_source(source.read_text(encoding="utf-8"), path=str(source))
    except Exception as exc:
        raise PrismExecutionError(
            "parse", _safe_error(exc, selected_model.api_key)
        ) from exc
    try:
        checked = check_program(
            parsed, modules=WorkspaceModuleLoader(project_root=project)
        )
    except Exception as exc:
        raise PrismExecutionError(
            "check", _safe_error(exc, selected_model.api_key)
        ) from exc
    try:
        typed = elaborate(checked)
    except Exception as exc:
        raise PrismExecutionError(
            "elaborate", _safe_error(exc, selected_model.api_key)
        ) from exc
    try:
        executable = compile_program(typed)
    except Exception as exc:
        raise PrismExecutionError(
            "compile", _safe_error(exc, selected_model.api_key)
        ) from exc

    effect_root = (artifact_root.resolve() / "prism-effects").resolve()
    if artifact_root.resolve() not in effect_root.parents:
        raise PrismExecutionError("resolve", "effect artifact path escapes run root")
    model_calls = {}
    recorder = ObservedRecorder(
        FileArtifactStore(effect_root), on_reasoning, model_calls
    )
    handler = LiteLLMEffectHandler(
        model=f"{selected_model.provider}/{selected_model.model_id}",
        completion=_completion_callable(selected_model, completion),
    )
    if on_reasoning:
        handler = ObservedHandler(
            model=f"{selected_model.provider}/{selected_model.model_id}",
            completion=_completion_callable(selected_model, completion),
            callback=on_reasoning,
            model_calls=model_calls,
        )
    if effect_handler is not None:
        # Only explicit package execute hooks can supply native implementations.
        # The hook already executes inside the same isolated worker boundary.
        handler = CompositeEffectHandler((effect_handler, handler))
    try:
        output = run_with_reasoning(
            executable,
            callback=on_reasoning,
            handler=handler,
            effect_recorder=recorder,
            entry_arguments={entry_argument: prepared_input["value"]},
        )
    except Exception as exc:
        raise PrismExecutionError(
            "runtime",
            _safe_error(exc, selected_model.api_key),
            effect_records=recorder.records,
        ) from exc

    return PrismExecutionResult(
        status=output.status,
        typed_result=output.result,
        trace=tuple(output.trace),
        effect_records=dict(output.effect_records),
        source_hash=_sha256(output.source_hash),
        module_hashes={
            name: _sha256(value)
            for name, value in output.metadata.get("module_hashes", {}).items()
        },
        diagnostics=tuple(item.message for item in output.diagnostics),
        effect_recorder=recorder,
        run_output=output,
    )


def response_text(response):
    """Read only the assistant's visible answer, excluding provider reasoning fields."""
    if hasattr(response, "model_dump"):
        response = response.model_dump(mode="json")
    choices = response.get("choices", []) if isinstance(response, Mapping) else []
    message = choices[0].get("message", {}) if choices else {}
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, Mapping):
        return json.dumps(content, ensure_ascii=False, indent=2)
    parsed = message.get("parsed")
    return (
        json.dumps(parsed, ensure_ascii=False, indent=2) if parsed is not None else None
    )


def observed_completion(completion, model_id, callback):
    """Observe direct model calls made by package execution/verification hooks."""

    def call(**arguments):
        call_id = uuid.uuid4().hex
        detail = {
            "model_id": model_id,
            "input_text": "\n\n".join(
                f"{message['role']}:\n{message['content']}"
                for message in arguments.get("messages", [])
            ),
        }

        def emit(status):
            callback(
                source_event_key=f"model:{call_id}:{status}",
                event_kind="model",
                observed_at=datetime.now(timezone.utc),
                stage="Model call",
                status=status,
                model_call=dict(detail),
            )

        emit("running")
        try:
            response = completion(**arguments)
        except Exception:
            emit("failed")
            raise
        detail["output_text"] = response_text(response)
        emit("completed")
        return response

    return call


class ObservedHandler:
    """Record the actual text messages and answer alongside each typed model effect."""

    def __init__(self, *, model, completion, callback, model_calls):
        self.model = model
        self.completion = completion
        self.callback = callback
        self.model_calls = model_calls

    def handles(self, symbol, effects):
        return symbol == "generate" and "AI.Generate" in effects

    def execute(self, request):
        detail = {"model_id": self.model}
        self.model_calls[request.call_id] = detail

        def complete(**arguments):
            detail["input_text"] = "\n\n".join(
                f"{message['role']}:\n{message['content']}"
                for message in arguments["messages"]
            )
            self.callback(
                source_event_key=f"model:{request.call_id}:running",
                event_kind="model",
                observed_at=datetime.now(timezone.utc),
                stage="Model call",
                status="running",
                model_call=dict(detail),
            )
            response = self.completion(**arguments)
            detail["output_text"] = response_text(response)
            return response

        return LiteLLMEffectHandler(model=self.model, completion=complete).execute(
            request
        )


class ObservedTrace(list):
    """Publish occurrence transitions when the runtime records them."""

    def __init__(self, callback):
        super().__init__()
        self.callback = callback
        self.statuses = {}
        self.identity = uuid.uuid4().hex

    def append(self, event):
        super().append(event)
        self.observe(len(self) - 1, event)

    def __setitem__(self, index, event):
        if index < 0:
            index += len(self)
        super().__setitem__(index, event)
        self.observe(index, event)

    def observe(self, index, event):
        if event.kind != "workflow-node" or event.outcome is None:
            return
        outcome = event.outcome
        if event.status == "rejected" or outcome.contract == "rejected":
            status = "rejected"
        elif outcome.execution == "failed":
            status = "failed"
        elif outcome.execution == "running":
            status = "running"
        elif outcome.contract == "satisfied":
            status = "completed"
        else:
            # A returned value is not completion until occurrence checks finish.
            return
        self.emit(index, event, status)

    def emit(self, index, event, status):
        if self.statuses.get(index) == status:
            return
        self.statuses[index] = status
        self.callback(
            source_event_key=f"reasoning-step:{self.identity}:{index}:{status}",
            event_kind="stage",
            observed_at=datetime.now(timezone.utc),
            stage="Reasoning step",
            status=status,
            reasoning_step={
                "name": event.name,
                "component": str(event.metadata.get("component", "")),
                "workflow": str(event.metadata.get("workflow_id", "")),
            },
        )

    def finish(self):
        for index, status in list(self.statuses.items()):
            if status == "running":
                self.emit(index, self[index], "interrupted")


def run_with_reasoning(
    program, *, callback=None, handler, effect_recorder, entry_arguments
):
    if callback is None:
        return run(
            program,
            handler=handler,
            effect_recorder=effect_recorder,
            entry_arguments=entry_arguments,
        )
    # The pinned Prism runtime has no public trace callback. Keep this adapter
    # local to one engine instance; never monkey-patch runtime globals.
    from prism.runtime.engine.execution import _Engine
    from prism.language.kernel import Kernel

    engine = _Engine(
        program,
        handler,
        Kernel(
            program.checked_module.environment
            if program.checked_module is not None
            else None
        ),
        None,
        effect_recorder,
        None,
        entry_arguments,
    )
    trace = ObservedTrace(callback)
    engine.trace = trace
    try:
        engine.preflight()
        output = engine.execute()
    finally:
        trace.finish()
    output.trace = list(trace)
    return output


class ObservedRecorder(EffectRecorder):
    def __init__(self, store, callback, model_calls=None):
        super().__init__(store)
        self.callback = callback
        self.model_calls = model_calls if model_calls is not None else {}

    def record(self, request, result):
        record = super().record(request, result)
        if (
            self.callback
            and request.symbol == "generate"
            and "AI.Generate" in request.effects
        ):
            value = result.value
            if isinstance(value, Ok):
                value = value.value
            if isinstance(value, GeneratedValue):
                value = value.value
            if isinstance(value, RecordValue):
                value = value.fields
            # Project named public summary fields, never replay artifacts or error strings.
            self.callback(
                source_event_key=f"model:{request.call_id}:result",
                event_kind="model",
                observed_at=datetime.now(timezone.utc),
                stage="Model result",
                status=record.observation.status,
                result=value,
                model_call=self.model_calls.pop(request.call_id, None),
                evidence_references=[record.observation.output_digest],
            )
        return record
