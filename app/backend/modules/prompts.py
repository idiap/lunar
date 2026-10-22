# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import json
import re
import uuid
from collections.abc import AsyncIterable
from typing import Any, AsyncGenerator, cast

from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse

from modules.ai_models import decrypt_api_key
from modules.model_configuration import model_connection
from modules.common import (
    authenticated_user,
    connect,
    parse_uuid,
    record_json,
    request_model,
)
from modules.schemas import (
    PromptDirectoryInput,
    PromptDirectoryMove,
    PromptInput,
    PromptUpdate,
    RunPromptInput,
)

VARIABLE_RE = re.compile(r"(?<!\{)\{([A-Za-z][A-Za-z0-9_]*)\}(?!\})")


def substitute_variables(template: str, variables: dict[str, str] | None = None) -> str:
    declared = set(VARIABLE_RE.findall(template))
    missing = declared - set(variables or {})
    if missing:
        raise ValueError(f"Missing values for variables: {', '.join(sorted(missing))}")
    result = VARIABLE_RE.sub(lambda match: (variables or {})[match.group(1)], template)
    return result.replace("{{", "{").replace("}}", "}")


def _prompt_json(row) -> dict:
    result = record_json(row)
    result.pop("user_id", None)
    return result


async def create_prompt(request: Request) -> JSONResponse:
    user = await authenticated_user(request)
    if isinstance(user, JSONResponse):
        return user
    body = await request_model(request, PromptInput)
    if isinstance(body, JSONResponse):
        return body
    connection = await connect()
    try:
        if body.directory_id is not None and not await connection.fetchval(
            "SELECT EXISTS(SELECT 1 FROM prompt_directories WHERE id = $1 AND user_id = $2)",
            body.directory_id,
            user["id"],
        ):
            return JSONResponse({"error": "Directory not found"}, status_code=404)
        row = await connection.fetchrow(
            """
            INSERT INTO prompts (id, user_id, name, content, directory_id)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id, name, content, directory_id, created_at, updated_at
            """,
            uuid.uuid4(),
            user["id"],
            body.name.strip(),
            body.content,
            body.directory_id,
        )
    finally:
        await connection.close()
    return JSONResponse(_prompt_json(row), status_code=201)


async def list_prompts(request: Request) -> JSONResponse:
    user = await authenticated_user(request)
    if isinstance(user, JSONResponse):
        return user
    limit = min(max(int(request.query_params.get("limit", "100")), 1), 500)
    offset = max(int(request.query_params.get("offset", "0")), 0)
    connection = await connect()
    try:
        rows = await connection.fetch(
            "SELECT id, name FROM prompts WHERE user_id = $1 ORDER BY created_at DESC LIMIT $2 OFFSET $3",
            user["id"],
            limit,
            offset,
        )
    finally:
        await connection.close()
    return JSONResponse([_prompt_json(row) for row in rows])


async def get_prompt(request: Request) -> JSONResponse:
    user = await authenticated_user(request)
    if isinstance(user, JSONResponse):
        return user
    prompt_id = parse_uuid(request.path_params["prompt_id"])
    if prompt_id is None:
        return JSONResponse({"error": "Prompt not found"}, status_code=404)
    connection = await connect()
    try:
        row = await connection.fetchrow(
            "SELECT id, name, content, directory_id, created_at, updated_at FROM prompts WHERE id = $1 AND user_id = $2",
            prompt_id,
            user["id"],
        )
    finally:
        await connection.close()
    if row is None:
        return JSONResponse({"error": "Prompt not found"}, status_code=404)
    return JSONResponse(_prompt_json(row))


async def update_prompt(request: Request) -> JSONResponse:
    user = await authenticated_user(request)
    if isinstance(user, JSONResponse):
        return user
    prompt_id = parse_uuid(request.path_params["prompt_id"])
    if prompt_id is None:
        return JSONResponse({"error": "Prompt not found"}, status_code=404)
    body = await request_model(request, PromptUpdate)
    if isinstance(body, JSONResponse):
        return body
    values = body.model_dump(exclude_unset=True)
    if not values:
        return await get_prompt(request)
    fields: list[str] = []
    args: list[object] = []
    for name in ("name", "content", "directory_id"):
        if name in values:
            args.append(values[name])
            fields.append(f"{name} = ${len(args)}")
    args.extend([prompt_id, user["id"]])
    connection = await connect()
    try:
        directory_id = values.get("directory_id")
        if directory_id is not None and not await connection.fetchval(
            "SELECT EXISTS(SELECT 1 FROM prompt_directories WHERE id = $1 AND user_id = $2)",
            directory_id,
            user["id"],
        ):
            return JSONResponse({"error": "Directory not found"}, status_code=404)
        row = await connection.fetchrow(
            f"""
            UPDATE prompts SET {', '.join(fields)}, updated_at = NOW()
            WHERE id = ${len(args) - 1} AND user_id = ${len(args)}
            RETURNING id, name, content, directory_id, created_at, updated_at
            """,
            *args,
        )
    finally:
        await connection.close()
    if row is None:
        return JSONResponse({"error": "Prompt not found"}, status_code=404)
    return JSONResponse(_prompt_json(row))


async def delete_prompt(request: Request) -> JSONResponse:
    user = await authenticated_user(request)
    if isinstance(user, JSONResponse):
        return user
    prompt_id = parse_uuid(request.path_params["prompt_id"])
    if prompt_id is None:
        return JSONResponse({"error": "Prompt not found"}, status_code=404)
    connection = await connect()
    try:
        result = await connection.execute(
            "DELETE FROM prompts WHERE id = $1 AND user_id = $2", prompt_id, user["id"]
        )
    finally:
        await connection.close()
    if result == "DELETE 0":
        return JSONResponse({"error": "Prompt not found"}, status_code=404)
    return JSONResponse({"success": True, "message": "Prompt deleted successfully"})


async def create_directory(request: Request) -> JSONResponse:
    user = await authenticated_user(request)
    if isinstance(user, JSONResponse):
        return user
    body = await request_model(request, PromptDirectoryInput)
    if isinstance(body, JSONResponse):
        return body
    connection = await connect()
    try:
        if body.parent_id is not None and not await connection.fetchval(
            "SELECT EXISTS(SELECT 1 FROM prompt_directories WHERE id = $1 AND user_id = $2)",
            body.parent_id,
            user["id"],
        ):
            return JSONResponse(
                {"error": "Parent directory not found"}, status_code=404
            )
        row = await connection.fetchrow(
            """
            INSERT INTO prompt_directories (id, user_id, name, parent_id)
            VALUES ($1, $2, $3, $4)
            RETURNING id, name, parent_id, created_at, updated_at
            """,
            uuid.uuid4(),
            user["id"],
            body.name.strip(),
            body.parent_id,
        )
    finally:
        await connection.close()
    return JSONResponse(_prompt_json(row), status_code=201)


async def get_directory(request: Request) -> JSONResponse:
    user = await authenticated_user(request)
    if isinstance(user, JSONResponse):
        return user
    directory_id = parse_uuid(request.path_params["directory_id"])
    if directory_id is None:
        return JSONResponse({"error": "Directory not found"}, status_code=404)
    connection = await connect()
    try:
        row = await connection.fetchrow(
            "SELECT id, name, parent_id, created_at, updated_at FROM prompt_directories WHERE id = $1 AND user_id = $2",
            directory_id,
            user["id"],
        )
    finally:
        await connection.close()
    if row is None:
        return JSONResponse({"error": "Directory not found"}, status_code=404)
    return JSONResponse(_prompt_json(row))


async def root_directories(request: Request) -> JSONResponse:
    user = await authenticated_user(request)
    if isinstance(user, JSONResponse):
        return user
    connection = await connect()
    try:
        rows = await connection.fetch(
            "SELECT id, name, parent_id, created_at, updated_at FROM prompt_directories WHERE user_id = $1 AND parent_id IS NULL ORDER BY name",
            user["id"],
        )
    finally:
        await connection.close()
    return JSONResponse([_prompt_json(row) for row in rows])


async def _contents(user_id, directory_id: uuid.UUID | None) -> dict | None:
    connection = await connect()
    try:
        directory = None
        breadcrumb = []
        if directory_id is not None:
            directory = await connection.fetchrow(
                "SELECT id, name, parent_id, created_at, updated_at FROM prompt_directories WHERE id = $1 AND user_id = $2",
                directory_id,
                user_id,
            )
            if directory is None:
                return None
            breadcrumb_rows = await connection.fetch(
                """
                WITH RECURSIVE ancestors AS (
                    SELECT id, name, parent_id, created_at, updated_at, 0 AS depth
                    FROM prompt_directories WHERE id = $1 AND user_id = $2
                    UNION ALL
                    SELECT d.id, d.name, d.parent_id, d.created_at, d.updated_at, a.depth + 1
                    FROM prompt_directories d JOIN ancestors a ON d.id = a.parent_id
                    WHERE d.user_id = $2
                )
                SELECT id, name, parent_id, created_at, updated_at
                FROM ancestors ORDER BY depth DESC
                """,
                directory_id,
                user_id,
            )
            breadcrumb = [_prompt_json(row) for row in breadcrumb_rows]
        if directory_id is None:
            directory_rows = await connection.fetch(
                "SELECT id, name, created_at, updated_at FROM prompt_directories WHERE user_id = $1 AND parent_id IS NULL ORDER BY name",
                user_id,
            )
            prompt_rows = await connection.fetch(
                "SELECT id, name, created_at, updated_at FROM prompts WHERE user_id = $1 AND directory_id IS NULL ORDER BY name",
                user_id,
            )
        else:
            directory_rows = await connection.fetch(
                "SELECT id, name, created_at, updated_at FROM prompt_directories WHERE user_id = $1 AND parent_id = $2 ORDER BY name",
                user_id,
                directory_id,
            )
            prompt_rows = await connection.fetch(
                "SELECT id, name, created_at, updated_at FROM prompts WHERE user_id = $1 AND directory_id = $2 ORDER BY name",
                user_id,
                directory_id,
            )
    finally:
        await connection.close()
    children = [dict(_prompt_json(row), type="directory") for row in directory_rows]
    children += [dict(_prompt_json(row), type="prompt") for row in prompt_rows]
    return {
        "directory": _prompt_json(directory) if directory else None,
        "breadcrumb": breadcrumb,
        "children": children,
    }


async def root_contents(request: Request) -> JSONResponse:
    user = await authenticated_user(request)
    if isinstance(user, JSONResponse):
        return user
    return JSONResponse(await _contents(user["id"], None))


async def directory_contents(request: Request) -> JSONResponse:
    user = await authenticated_user(request)
    if isinstance(user, JSONResponse):
        return user
    directory_id = parse_uuid(request.path_params["directory_id"])
    if directory_id is None:
        return JSONResponse({"error": "Directory not found"}, status_code=404)
    contents = await _contents(user["id"], directory_id)
    if contents is None:
        return JSONResponse({"error": "Directory not found"}, status_code=404)
    return JSONResponse(contents)


async def move_directory(request: Request) -> JSONResponse:
    user = await authenticated_user(request)
    if isinstance(user, JSONResponse):
        return user
    directory_id = parse_uuid(request.path_params["directory_id"])
    if directory_id is None:
        return JSONResponse({"error": "Directory not found"}, status_code=404)
    body = await request_model(request, PromptDirectoryMove)
    if isinstance(body, JSONResponse):
        return body
    if body.parent_id == directory_id:
        return JSONResponse(
            {"error": "A directory cannot contain itself"}, status_code=409
        )
    connection = await connect()
    try:
        if body.parent_id is not None:
            descendant = await connection.fetchval(
                """
                WITH RECURSIVE descendants AS (
                    SELECT id FROM prompt_directories WHERE parent_id = $1 AND user_id = $2
                    UNION ALL
                    SELECT d.id FROM prompt_directories d JOIN descendants x ON d.parent_id = x.id
                    WHERE d.user_id = $2
                ) SELECT EXISTS(SELECT 1 FROM descendants WHERE id = $3)
                """,
                directory_id,
                user["id"],
                body.parent_id,
            )
            if descendant:
                return JSONResponse(
                    {"error": "A directory cannot be moved into its descendant"},
                    status_code=409,
                )
        row = await connection.fetchrow(
            """
            UPDATE prompt_directories SET parent_id = $1, updated_at = NOW()
            WHERE id = $2 AND user_id = $3
            RETURNING id, name, parent_id, created_at, updated_at
            """,
            body.parent_id,
            directory_id,
            user["id"],
        )
    finally:
        await connection.close()
    if row is None:
        return JSONResponse({"error": "Directory not found"}, status_code=404)
    return JSONResponse(_prompt_json(row))


async def delete_directory(request: Request) -> JSONResponse:
    user = await authenticated_user(request)
    if isinstance(user, JSONResponse):
        return user
    directory_id = parse_uuid(request.path_params["directory_id"])
    if directory_id is None:
        return JSONResponse({"error": "Directory not found"}, status_code=404)
    connection = await connect()
    try:
        result = await connection.execute(
            "DELETE FROM prompt_directories WHERE id = $1 AND user_id = $2",
            directory_id,
            user["id"],
        )
    finally:
        await connection.close()
    if result == "DELETE 0":
        return JSONResponse({"error": "Directory not found"}, status_code=404)
    return JSONResponse({"success": True, "message": "Directory deleted successfully"})


async def _prompt_events(body: RunPromptInput, user_id) -> AsyncGenerator[str, None]:
    try:
        prompt = substitute_variables(body.prompt, body.variables)
    except ValueError as error:
        yield f"data: {json.dumps({'type': 'error', 'error': str(error)})}\n\n"
        return
    connection = await connect()
    try:
        model = await connection.fetchrow(
            "SELECT provider, model_id, api_base, api_version, encrypted_api_key, config FROM ai_models WHERE id = $1 AND user_id = $2",
            body.ai_model_id,
            user_id,
        )
    finally:
        await connection.close()
    if model is None:
        yield f"data: {json.dumps({'type': 'error', 'error': 'AI model not found'})}\n\n"
        return
    try:
        import litellm

        params = dict(model["config"] or {})
        params.update(body.parameters or {})
        kwargs = {
            "model": f"{model['provider']}/{model['model_id']}",
            "messages": [{"role": "user", "content": prompt}],
            "api_key": decrypt_api_key(model["encrypted_api_key"]),
            "stream": True,
            **params,
        }
        kwargs.pop("api_base", None)
        kwargs.pop("api_version", None)
        kwargs.update(
            model_connection(
                model["provider"],
                model["model_id"],
                model["api_base"],
                model["api_version"],
            )
        )
        response = cast(AsyncIterable[Any], await litellm.acompletion(**kwargs))
        async for chunk in response:
            choices = chunk.get("choices", [])
            content = choices[0].get("delta", {}).get("content") if choices else None
            if content:
                yield f"data: {json.dumps({'type': 'text-delta', 'delta': content})}\n\n"
        yield f"data: {json.dumps({'type': 'finish'})}\n\n"
        yield "data: [DONE]\n\n"
    except Exception as error:
        yield f"data: {json.dumps({'type': 'error', 'error': str(error)})}\n\n"


async def run_prompt(request: Request):
    user = await authenticated_user(request)
    if isinstance(user, JSONResponse):
        return user
    body = await request_model(request, RunPromptInput)
    if isinstance(body, JSONResponse):
        return body
    return StreamingResponse(
        _prompt_events(body, user["id"]),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


def register_prompt_routes(mcp: FastMCP) -> None:
    mcp.custom_route("/api/prompts", methods=["GET"])(list_prompts)
    mcp.custom_route("/api/prompts", methods=["POST"])(create_prompt)
    mcp.custom_route("/api/prompts/run", methods=["POST"])(run_prompt)
    mcp.custom_route("/api/prompts/root/contents", methods=["GET"])(root_contents)
    mcp.custom_route("/api/prompts/directories", methods=["POST"])(create_directory)
    mcp.custom_route("/api/prompts/directories/root", methods=["GET"])(root_directories)
    mcp.custom_route(
        "/api/prompts/directories/{directory_id}/contents", methods=["GET"]
    )(directory_contents)
    mcp.custom_route("/api/prompts/directories/{directory_id}/move", methods=["PUT"])(
        move_directory
    )
    mcp.custom_route("/api/prompts/directories/{directory_id}", methods=["GET"])(
        get_directory
    )
    mcp.custom_route("/api/prompts/directories/{directory_id}", methods=["DELETE"])(
        delete_directory
    )
    mcp.custom_route("/api/prompts/{prompt_id}", methods=["GET"])(get_prompt)
    mcp.custom_route("/api/prompts/{prompt_id}", methods=["PUT"])(update_prompt)
    mcp.custom_route("/api/prompts/{prompt_id}", methods=["DELETE"])(delete_prompt)
