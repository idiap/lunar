# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import asyncio
import json
import re
import uuid
from collections.abc import AsyncGenerator, AsyncIterable, Mapping, Sequence
from typing import Any, Awaitable, Callable, cast

from ag_ui.core import (
    CustomEvent,
    RunAgentInput,
    RunErrorEvent,
    RunFinishedEvent,
    RunStartedEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
    ToolCallArgsEvent,
    ToolCallEndEvent,
    ToolCallResultEvent,
    ToolCallStartEvent,
)
from ag_ui.encoder import EventEncoder
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field, ValidationError, field_validator
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse

from modules.ai_models import decrypt_api_key
from modules.model_configuration import model_connection
from modules.common import (
    authenticated_user,
    connect,
    json_value,
    parse_uuid,
    request_model,
)

MAX_TOOL_ROUNDS = 12
MODEL_TOOL_RESULT_CHAR_LIMIT = 12_000
DEFAULT_PLANNER_TOOLS = ("planner",)

LUNAR_INSTRUCTIONS = """Use `planner` for work in the selected package. It automatically plans,
reviews, executes supported work, evaluates delivery, and publishes the exact released
artifact when authenticated. Present its released result and report reference faithfully.
For clarification, ask its questions and pass new facts with its opaque continuation_id.
Preserve explicit planning-only requests. Report blocked work, execution limitations,
and publication errors truthfully. Never invent an artifact, owner, or report URL.
"""


def _planning_only_boundary_requested(messages: Sequence[Mapping[str, Any]]) -> bool:
    """Return whether the latest user request explicitly stops before execution."""

    latest = next(
        (
            str(message.get("content", ""))
            for message in reversed(messages)
            if message.get("role") == "user" and isinstance(message.get("content"), str)
        ),
        "",
    ).casefold()
    explicit_boundary = bool(
        re.search(
            r"\b(?:(?:plan|planning)[ -]only|do not execute|don't execute|"
            r"(?:only|just)\s+(?:plan|review|explain|inspect))\b",
            latest,
        )
    )
    boundary_verb = bool(
        re.match(r"^\s*(?:please\s+)?(?:plan|review|explain|inspect)\b", latest)
    )
    execution_verb = bool(
        re.search(
            r"\b(?:execute|run|perform|apply|generate|create|build|produce|"
            r"prepare|assemble)\b",
            latest,
        )
    )
    return explicit_boundary or (boundary_verb and not execution_verb)


class ChatConfiguration(BaseModel):
    ai_model_id: uuid.UUID = Field(alias="aiModelId")
    chat_id: uuid.UUID | None = Field(default=None, alias="chatId")
    enabled_tools: list[str] = Field(
        default_factory=lambda: list(DEFAULT_PLANNER_TOOLS), alias="enabledTools"
    )

    @field_validator("enabled_tools")
    @classmethod
    def unique_tools(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(value))


def chat_configuration(value: Any) -> ChatConfiguration:
    return ChatConfiguration.model_validate(value if isinstance(value, Mapping) else {})


def tool_descriptor(tool: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "name": tool["name"],
        "description": tool.get("description") or "",
        "parameters": tool.get("inputSchema") or {"type": "object"},
        "source": "mcp",
        "default_enabled": tool["name"] in DEFAULT_PLANNER_TOOLS,
    }


def fallback_chat_title(prompt: str) -> str:
    words = re.findall(r"[\w]+(?:[-'][\w]+)*", prompt, flags=re.UNICODE)
    title = " ".join(words[:6]).strip()
    return title[:60] or "New chat"


def _clean_generated_title(value: str, prompt: str) -> str:
    first_line = value.strip().splitlines()[0] if value.strip() else ""
    title = re.sub(r"^title\s*:\s*", "", first_line, flags=re.IGNORECASE)
    title = title.strip(" \t\"'“”‘’#*.-")
    title = " ".join(title.split()[:6])
    return title[:60].rstrip() or fallback_chat_title(prompt)


def _value(source: Any, name: str, default: Any = None) -> Any:
    if isinstance(source, Mapping):
        return source.get(name, default)
    return getattr(source, name, default)


def _litellm_messages(messages: Sequence[Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    tool_names: dict[str, str] = {}
    completed_calls = {
        str(message.tool_call_id) for message in messages if message.role == "tool"
    }
    for message in messages:
        role = message.role
        if role == "activity":
            continue
        if role == "reasoning":
            role = "assistant"
        content = message.content
        if role == "tool":
            content = _model_tool_result_content(
                tool_names.get(str(message.tool_call_id), ""), content
            )
        converted: dict[str, Any] = {"role": role, "content": content}
        name = getattr(message, "name", None)
        if name:
            converted["name"] = name
        if role == "tool":
            converted["tool_call_id"] = message.tool_call_id
        tool_calls = getattr(message, "tool_calls", None)
        if tool_calls:
            converted["tool_calls"] = [
                {
                    "id": tool_call.id,
                    "type": "function",
                    "function": {
                        "name": tool_call.function.name,
                        "arguments": tool_call.function.arguments,
                    },
                }
                for tool_call in tool_calls
            ]
            tool_names.update(
                {
                    str(tool_call.id): str(tool_call.function.name)
                    for tool_call in tool_calls
                }
            )
        result.append(converted)
        for tool_call in tool_calls or ():
            if str(tool_call.id) not in completed_calls:
                result.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(
                            {
                                "status": "interrupted",
                                "execution_performed": False,
                                "error": "Historical tool call has no saved result; it was not resumed.",
                            }
                        ),
                    }
                )
    return result


def _json_ready(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(by_alias=True, exclude_none=True)
    if isinstance(value, Mapping):
        return {key: _json_ready(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_ready(item) for item in value]
    if isinstance(value, uuid.UUID):
        return str(value)
    return value


def _tool_result_content(value: Any) -> str:
    return json.dumps(_json_ready(value), ensure_ascii=False, default=str)


def _structured_tool_payload(value: Any) -> Any:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return value
    normalized = _json_ready(value)
    if (
        isinstance(normalized, list)
        and len(normalized) == 2
        and isinstance(normalized[1], Mapping)
    ):
        normalized = normalized[1]
    if isinstance(normalized, Mapping):
        structured = normalized.get("structuredContent") or normalized.get(
            "structured_content"
        )
        if isinstance(structured, Mapping):
            normalized = structured
        elif set(normalized) == {"result"}:
            normalized = normalized["result"]
        elif isinstance(normalized.get("content"), list):
            content = normalized["content"]
            if content and isinstance(content[0], Mapping):
                text = content[0].get("text")
                if isinstance(text, str):
                    try:
                        normalized = json.loads(text)
                    except json.JSONDecodeError:
                        pass
    if isinstance(normalized, Mapping) and set(normalized) == {"result"}:
        return normalized["result"]
    return normalized


def _compact_value(value: Any, *, depth: int = 0) -> Any:
    if depth >= 10:
        return "[nested value omitted]"
    if isinstance(value, Mapping):
        return {
            str(key): _compact_value(item, depth=depth + 1)
            for key, item in list(value.items())[:40]
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        rows = [_compact_value(item, depth=depth + 1) for item in value[:12]]
        if len(value) > 12:
            rows.append({"omitted_items": len(value) - 12})
        return rows
    if isinstance(value, str) and len(value) > 2_000:
        return value[:2_000] + "…[truncated]"
    return value


def _model_tool_projection(tool_name: str, payload: Any) -> Any:
    if tool_name == "planner" and isinstance(payload, Mapping):
        return {
            key: value
            for key, value in payload.items()
            if key not in {"reasoning", "plan"}
        }
    return _compact_value(payload)


def _model_tool_result_content(tool_name: str, value: Any) -> str:
    payload = _structured_tool_payload(value)
    compact = _model_tool_projection(tool_name, payload)
    encoded = json.dumps(compact, ensure_ascii=False, default=str)
    if len(encoded) <= MODEL_TOOL_RESULT_CHAR_LIMIT:
        return encoded
    reduced = _compact_value(compact, depth=2)
    encoded = json.dumps(reduced, ensure_ascii=False, default=str)
    if len(encoded) <= MODEL_TOOL_RESULT_CHAR_LIMIT:
        return encoded
    return json.dumps(
        {
            "tool": tool_name,
            "result_truncated": True,
            "summary": encoded[: MODEL_TOOL_RESULT_CHAR_LIMIT - 100],
        },
        ensure_ascii=False,
    )


def _selected_chat_version(user_id):
    from domain_packages.context import CURRENT_VERSION, require_context

    return (
        require_context(user_id).version_id
        if CURRENT_VERSION.get() is not None
        else None
    )


async def _model_for_user(model_id: uuid.UUID, user_id: uuid.UUID):
    connection = await connect()
    try:
        return await connection.fetchrow(
            """
            SELECT id,provider, model_id, api_base, api_version,
                   encrypted_api_key, config
            FROM ai_models WHERE id = $1 AND user_id = $2
            """,
            model_id,
            user_id,
        )
    finally:
        await connection.close()


def _chat_json(
    row: Mapping[str, Any], include_messages: bool = False
) -> dict[str, Any]:
    result = {
        "id": str(row["id"]),
        "title": row["title"],
        "version_id": str(row["version_id"]) if row.get("version_id") else None,
        "created_at": row["created_at"].isoformat(),
        "updated_at": row["updated_at"].isoformat(),
    }
    if include_messages:
        result["messages"] = json_value(row["messages"], [])
        result["pending_interrupt"] = json_value(row["pending_interrupt"], None)
    return result


async def _chat_for_user(chat_id: uuid.UUID, user_id: uuid.UUID):
    connection = await connect()
    try:
        return await connection.fetchrow(
            """
            SELECT id,version_id,title,messages,pending_interrupt,created_at,updated_at
            FROM chats WHERE id = $1 AND user_id = $2 AND version_id IS NOT DISTINCT FROM $3
            """,
            chat_id,
            user_id,
            _selected_chat_version(user_id),
        )
    finally:
        await connection.close()


async def _create_chat(
    user_id: uuid.UUID, title: str, messages: Sequence[Mapping[str, Any]]
):
    connection = await connect()
    try:
        return await connection.fetchrow(
            """
            INSERT INTO chats (id, user_id, title, messages,version_id)
            VALUES ($1, $2, $3, $4::jsonb,$5)
            RETURNING id,version_id,title,messages,pending_interrupt,created_at,updated_at
            """,
            uuid.uuid4(),
            user_id,
            title,
            json.dumps(list(messages), ensure_ascii=False),
            _selected_chat_version(user_id),
        )
    finally:
        await connection.close()


async def _save_chat_messages(
    chat_id: uuid.UUID,
    user_id: uuid.UUID,
    messages: Sequence[Mapping[str, Any]],
    pending_interrupt: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    connection = await connect()
    try:
        row = await connection.fetchrow(
            """
            UPDATE chats
            SET messages = $1::jsonb,
                pending_interrupt = $2::jsonb,
                updated_at = NOW()
            WHERE id = $3 AND user_id = $4 AND version_id IS NOT DISTINCT FROM $5
            RETURNING id,version_id,title,created_at,updated_at
            """,
            json.dumps(list(messages), ensure_ascii=False),
            (
                json.dumps(dict(pending_interrupt), ensure_ascii=False)
                if pending_interrupt is not None
                else None
            ),
            chat_id,
            user_id,
            _selected_chat_version(user_id),
        )
    finally:
        await connection.close()
    if row is None:
        raise ValueError("Chat not found")
    return _chat_json(row)


async def _generate_chat_title(model: Mapping[str, Any], prompt: str) -> str:
    try:
        import litellm

        arguments = _completion_arguments(
            model,
            [
                {
                    "role": "system",
                    "content": (
                        "Create a specific chat title of at most six words. "
                        "Return only the title, without quotes or punctuation."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            [],
        )
        arguments["stream"] = False
        for option in ("response_format", "stream_options", "tool_choice"):
            arguments.pop(option, None)
        response = await litellm.acompletion(**arguments)
        choices = _value(response, "choices", [])
        message = _value(choices[0], "message", {}) if choices else {}
        content = _value(message, "content", "") or ""
        return _clean_generated_title(str(content), prompt)
    except Exception:
        return fallback_chat_title(prompt)


def _completion_arguments(model: Mapping[str, Any], messages, tools) -> dict[str, Any]:
    arguments = dict(json_value(model["config"], {}) or {})
    arguments.update(
        {
            "model": f"{model['provider']}/{model['model_id']}",
            "messages": messages,
            "api_key": decrypt_api_key(model["encrypted_api_key"]),
            "stream": True,
        }
    )
    if tools:
        arguments["tools"] = tools
    else:
        arguments.pop("tools", None)
    arguments.pop("api_base", None)
    arguments.pop("api_version", None)
    arguments.update(
        model_connection(
            model["provider"],
            model["model_id"],
            model["api_base"],
            model["api_version"],
        )
    )
    return arguments


async def _chat_events(
    body: RunAgentInput,
    model: Mapping[str, Any],
    enabled_tools: Mapping[str, Mapping[str, Any]],
    mcp: FastMCP,
    encoder: EventEncoder,
    persist_messages: (
        Callable[[list[dict[str, Any]]], Awaitable[dict[str, Any]]] | None
    ) = None,
    principal: str | None = None,
) -> AsyncGenerator[str, None]:
    yield encoder.encode(
        RunStartedEvent(
            thread_id=body.thread_id,
            run_id=body.run_id,
            parent_run_id=body.parent_run_id,
        )
    )
    conversation_messages = _litellm_messages(body.messages)
    messages = [
        {"role": "system", "content": LUNAR_INSTRUCTIONS},
        *conversation_messages,
    ]
    protocol_messages = [_json_ready(message) for message in body.messages]
    model_tools = [
        {
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool.get("description") or "",
                "parameters": tool.get("inputSchema") or {"type": "object"},
            },
        }
        for tool in enabled_tools.values()
    ]

    try:
        import litellm

        for _ in range(MAX_TOOL_ROUNDS):
            message_id = str(uuid.uuid4())
            yield encoder.encode(
                TextMessageStartEvent(message_id=message_id, role="assistant")
            )
            content_parts: list[str] = []
            pending_calls: dict[int, dict[str, str]] = {}
            completion_arguments = _completion_arguments(model, messages, model_tools)
            response = cast(
                AsyncIterable[Any],
                await litellm.acompletion(**completion_arguments),
            )
            async for chunk in response:
                choices = _value(chunk, "choices", [])
                if not choices:
                    continue
                delta = _value(choices[0], "delta", {})
                content = _value(delta, "content")
                if content:
                    content_parts.append(content)
                    yield encoder.encode(
                        TextMessageContentEvent(message_id=message_id, delta=content)
                    )
                for tool_call in _value(delta, "tool_calls", []) or []:
                    index = int(_value(tool_call, "index", 0))
                    pending = pending_calls.setdefault(
                        index, {"id": "", "name": "", "arguments": ""}
                    )
                    pending["id"] += _value(tool_call, "id", "") or ""
                    function = _value(tool_call, "function", {})
                    pending["name"] += _value(function, "name", "") or ""
                    pending["arguments"] += _value(function, "arguments", "") or ""

            yield encoder.encode(TextMessageEndEvent(message_id=message_id))
            if not pending_calls:
                protocol_messages.append(
                    {
                        "id": message_id,
                        "role": "assistant",
                        "content": "".join(content_parts),
                    }
                )
                if persist_messages:
                    saved_chat = await persist_messages(protocol_messages)
                    yield encoder.encode(
                        CustomEvent(name="chat_saved", value=saved_chat)
                    )
                yield encoder.encode(
                    RunFinishedEvent(thread_id=body.thread_id, run_id=body.run_id)
                )
                return

            assistant_calls = []
            for index in sorted(pending_calls):
                call = pending_calls[index]
                call_id = call["id"] or str(uuid.uuid4())
                call["id"] = call_id
                assistant_calls.append(
                    {
                        "id": call_id,
                        "type": "function",
                        "function": {
                            "name": call["name"],
                            "arguments": call["arguments"],
                        },
                    }
                )
                yield encoder.encode(
                    ToolCallStartEvent(
                        tool_call_id=call_id,
                        tool_call_name=call["name"],
                        parent_message_id=message_id,
                    )
                )
                if call["arguments"]:
                    yield encoder.encode(
                        ToolCallArgsEvent(tool_call_id=call_id, delta=call["arguments"])
                    )
                yield encoder.encode(ToolCallEndEvent(tool_call_id=call_id))

            protocol_messages.append(
                {
                    "id": message_id,
                    "role": "assistant",
                    "content": "".join(content_parts) or None,
                    "toolCalls": assistant_calls,
                }
            )
            messages.append(
                {
                    "role": "assistant",
                    "content": "".join(content_parts) or None,
                    "tool_calls": assistant_calls,
                }
            )
            for index in sorted(pending_calls):
                call = pending_calls[index]
                result_message_id = str(uuid.uuid4())
                try:
                    if call["name"] != "planner" or call["name"] not in enabled_tools:
                        raise PermissionError("Tool is not enabled for this chat run")
                    arguments = json.loads(call["arguments"] or "{}")
                    if not isinstance(arguments, dict):
                        raise ValueError("Tool arguments must be a JSON object")
                    from planner import run_pipeline
                    from planner_contract import PlannerInput

                    arguments = PlannerInput.model_validate(arguments).model_dump(
                        exclude_none=True
                    )
                    observations = asyncio.Queue()

                    async def observe(snapshot):
                        await observations.put(snapshot)

                    async def execute():
                        try:
                            return await run_pipeline(
                                {**arguments, "ai_model_id": str(model["id"])},
                                principal=principal,
                                channel="chat",
                                observe=observe,
                                planning_only=_planning_only_boundary_requested(
                                    conversation_messages
                                ),
                            )
                        finally:
                            await observations.put(None)

                    worker = asyncio.create_task(execute())
                    try:
                        while True:
                            observation = await observations.get()
                            if observation is None:
                                break
                            yield encoder.encode(
                                CustomEvent(
                                    name="planner_reasoning",
                                    value={
                                        "tool_call_id": call["id"],
                                        "snapshot": observation,
                                    },
                                )
                            )
                        result = await worker
                    finally:
                        if not worker.done():
                            worker.cancel()
                            await asyncio.gather(worker, return_exceptions=True)
                    result_content = _tool_result_content(result)
                    model_result_content = _model_tool_result_content(
                        call["name"], result
                    )
                except Exception as error:
                    result_content = json.dumps(
                        {"error": str(error), "tool": call["name"]},
                        ensure_ascii=False,
                    )
                    model_result_content = result_content
                yield encoder.encode(
                    ToolCallResultEvent(
                        message_id=result_message_id,
                        tool_call_id=call["id"],
                        content=result_content,
                    )
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call["id"],
                        "content": model_result_content,
                    }
                )
                protocol_messages.append(
                    {
                        "id": result_message_id,
                        "role": "tool",
                        "toolCallId": call["id"],
                        "content": result_content,
                    }
                )

        raise RuntimeError("The model exceeded the tool-call round limit")
    except Exception as error:
        if persist_messages:
            try:
                saved_chat = await persist_messages(protocol_messages)
                yield encoder.encode(CustomEvent(name="chat_saved", value=saved_chat))
            except Exception as persistence_error:
                error = RuntimeError(
                    f"{error}; chat could not be saved: {persistence_error}"
                )
        yield encoder.encode(RunErrorEvent(message=str(error), code="CHAT_RUN_FAILED"))


async def list_chat_tools(request: Request, mcp: FastMCP) -> JSONResponse:
    user = await authenticated_user(request)
    if isinstance(user, JSONResponse):
        return user
    tools = await mcp.list_tools()
    return JSONResponse(
        [
            tool_descriptor(tool.model_dump(by_alias=True, exclude_none=True))
            for tool in tools
        ]
    )


async def list_chats(request: Request) -> JSONResponse:
    user = await authenticated_user(request)
    if isinstance(user, JSONResponse):
        return user
    connection = await connect()
    try:
        rows = await connection.fetch(
            """
            SELECT id,version_id,title,created_at,updated_at
            FROM chats WHERE user_id = $1 AND version_id IS NOT DISTINCT FROM $2
            ORDER BY updated_at DESC
            """,
            user["id"],
            _selected_chat_version(user["id"]),
        )
    finally:
        await connection.close()
    return JSONResponse([_chat_json(row) for row in rows])


async def chat_context(request):
    user = await authenticated_user(request)
    if isinstance(user, JSONResponse):
        return user
    identity = parse_uuid(request.path_params["chat_id"])
    if identity is None:
        return JSONResponse({"error": "Chat not found"}, status_code=404)
    connection = await connect()
    try:
        row = await connection.fetchrow(
            "SELECT version_id FROM chats WHERE id=$1 AND user_id=$2",
            identity,
            user["id"],
        )
        if row is None:
            return JSONResponse({"error": "Chat not found"}, status_code=404)
        return JSONResponse(
            {"version_id": str(row["version_id"]) if row["version_id"] else None}
        )
    finally:
        await connection.close()


async def get_chat(request: Request) -> JSONResponse:
    user = await authenticated_user(request)
    if isinstance(user, JSONResponse):
        return user
    chat_id = parse_uuid(request.path_params["chat_id"])
    if chat_id is None:
        return JSONResponse({"error": "Chat not found"}, status_code=404)
    row = await _chat_for_user(chat_id, user["id"])
    if row is None:
        return JSONResponse({"error": "Chat not found"}, status_code=404)
    return JSONResponse(_chat_json(row, include_messages=True))


async def delete_chat(request: Request) -> JSONResponse:
    user = await authenticated_user(request)
    if isinstance(user, JSONResponse):
        return user
    chat_id = parse_uuid(request.path_params["chat_id"])
    if chat_id is None:
        return JSONResponse({"error": "Chat not found"}, status_code=404)
    connection = await connect()
    try:
        result = await connection.execute(
            "DELETE FROM chats WHERE id = $1 AND user_id = $2 AND version_id IS NOT DISTINCT FROM $3",
            chat_id,
            user["id"],
            _selected_chat_version(user["id"]),
        )
    finally:
        await connection.close()
    if result == "DELETE 0":
        return JSONResponse({"error": "Chat not found"}, status_code=404)
    return JSONResponse({"success": True, "message": "Chat deleted successfully"})


async def run_chat(request: Request, mcp: FastMCP):
    user = await authenticated_user(request)
    if isinstance(user, JSONResponse):
        return user
    body = await request_model(request, RunAgentInput)
    if isinstance(body, JSONResponse):
        return body
    try:
        configuration = chat_configuration(body.forwarded_props)
    except ValidationError as error:
        return JSONResponse(
            {"error": "Invalid chat configuration", "details": error.errors()},
            status_code=422,
        )

    available = {
        tool.name: tool.model_dump(by_alias=True, exclude_none=True)
        for tool in await mcp.list_tools()
    }
    unknown = sorted(set(configuration.enabled_tools) - set(available))
    if unknown:
        return JSONResponse(
            {"error": f"Unknown chat tools: {', '.join(unknown)}"}, status_code=422
        )
    model = await _model_for_user(configuration.ai_model_id, user["id"])
    if model is None:
        return JSONResponse({"error": "AI model not found"}, status_code=404)

    chat_id = configuration.chat_id
    if chat_id is None:
        first_prompt = next(
            (
                message.content
                for message in body.messages
                if message.role == "user" and isinstance(message.content, str)
            ),
            "",
        )
        if not first_prompt.strip():
            return JSONResponse(
                {"error": "A first user message is required"}, status_code=422
            )
        title = await _generate_chat_title(model, first_prompt)
        chat = await _create_chat(
            user["id"], title, [_json_ready(message) for message in body.messages]
        )
        if chat is None:
            return JSONResponse({"error": "Could not create chat"}, status_code=500)
        chat_id = chat["id"]
    elif await _chat_for_user(chat_id, user["id"]) is None:
        return JSONResponse({"error": "Chat not found"}, status_code=404)

    async def persist_messages(messages: list[dict[str, Any]]) -> dict[str, Any]:
        return await _save_chat_messages(chat_id, user["id"], messages)

    encoder = EventEncoder(accept=request.headers.get("accept") or "")
    enabled = {name: available[name] for name in configuration.enabled_tools}
    return StreamingResponse(
        _chat_events(
            body,
            model,
            enabled,
            mcp,
            encoder,
            persist_messages=persist_messages,
            principal=str(user["id"]),
        ),
        media_type=encoder.get_content_type(),
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


def register_chat_routes(mcp: FastMCP) -> None:
    async def tools_route(request: Request) -> JSONResponse:
        return await list_chat_tools(request, mcp)

    async def chat_route(request: Request):
        return await run_chat(request, mcp)

    mcp.custom_route("/api/chat/tools", methods=["GET"])(tools_route)
    mcp.custom_route("/api/chats/{chat_id}/context", methods=["GET"])(chat_context)
    mcp.custom_route("/api/chats", methods=["GET"])(list_chats)
    mcp.custom_route("/api/chats/{chat_id}", methods=["GET"])(get_chat)
    mcp.custom_route("/api/chats/{chat_id}", methods=["DELETE"])(delete_chat)
    mcp.custom_route("/api/chat", methods=["POST"])(chat_route)
