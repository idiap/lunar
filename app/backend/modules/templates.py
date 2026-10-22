# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import uuid

from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from modules.common import (
    authenticated_user,
    connect,
    parse_uuid,
    record_json,
    request_model,
)
from modules.schemas import TemplateInput, TemplateUpdate
from reporting.service import TemplateValidationError, parse_template


def _template_json(row) -> dict:
    result = record_json(row)
    result.pop("user_id", None)
    try:
        result["placeholder_inventory"] = parse_template(result.get("content") or "")
        result["template_errors"] = []
    except TemplateValidationError as exc:
        result["placeholder_inventory"] = None
        result["template_errors"] = exc.errors
    return result


async def create_template(request: Request) -> JSONResponse:
    user = await authenticated_user(request)
    if isinstance(user, JSONResponse):
        return user
    body = await request_model(request, TemplateInput)
    if isinstance(body, JSONResponse):
        return body
    try:
        parse_template(body.content)
    except TemplateValidationError as exc:
        return JSONResponse(
            {"error": "Invalid template", "details": exc.errors}, status_code=422
        )
    connection = await connect()
    try:
        row = await connection.fetchrow(
            """
            INSERT INTO templates (id, user_id, name, content, agent)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id, name, content, agent, created_at, updated_at
            """,
            uuid.uuid4(),
            user["id"],
            body.name.strip(),
            body.content,
            body.agent,
        )
    finally:
        await connection.close()
    return JSONResponse(_template_json(row), status_code=201)


async def list_templates(request: Request) -> JSONResponse:
    user = await authenticated_user(request)
    if isinstance(user, JSONResponse):
        return user
    raw_limit = request.query_params.get("limit", "100")
    limit = None if raw_limit.lower() == "none" else min(max(int(raw_limit), 1), 500)
    connection = await connect()
    try:
        if limit is None:
            rows = await connection.fetch(
                "SELECT id, name, content, agent, created_at, updated_at FROM templates WHERE user_id = $1 ORDER BY created_at DESC",
                user["id"],
            )
        else:
            rows = await connection.fetch(
                "SELECT id, name, content, agent, created_at, updated_at FROM templates WHERE user_id = $1 ORDER BY created_at DESC LIMIT $2",
                user["id"],
                limit,
            )
    finally:
        await connection.close()
    return JSONResponse([_template_json(row) for row in rows])


async def get_template(request: Request) -> JSONResponse:
    user = await authenticated_user(request)
    if isinstance(user, JSONResponse):
        return user
    template_id = parse_uuid(request.path_params["template_id"])
    if template_id is None:
        return JSONResponse({"error": "Template not found"}, status_code=404)
    connection = await connect()
    try:
        row = await connection.fetchrow(
            "SELECT id, name, content, agent, created_at, updated_at FROM templates WHERE id = $1 AND user_id = $2",
            template_id,
            user["id"],
        )
    finally:
        await connection.close()
    if row is None:
        return JSONResponse({"error": "Template not found"}, status_code=404)
    return JSONResponse(_template_json(row))


async def update_template(request: Request) -> JSONResponse:
    user = await authenticated_user(request)
    if isinstance(user, JSONResponse):
        return user
    template_id = parse_uuid(request.path_params["template_id"])
    if template_id is None:
        return JSONResponse({"error": "Template not found"}, status_code=404)
    body = await request_model(request, TemplateUpdate)
    if isinstance(body, JSONResponse):
        return body
    values = body.model_dump(exclude_unset=True)
    if not values:
        return await get_template(request)
    if "content" in values:
        try:
            parse_template(values["content"])
        except TemplateValidationError as exc:
            return JSONResponse(
                {"error": "Invalid template", "details": exc.errors}, status_code=422
            )
    fields: list[str] = []
    args: list[object] = []
    for name in ("name", "content", "agent"):
        if name in values:
            args.append(values[name])
            fields.append(f"{name} = ${len(args)}")
    args.extend([template_id, user["id"]])
    connection = await connect()
    try:
        row = await connection.fetchrow(
            f"""
            UPDATE templates SET {', '.join(fields)}, updated_at = NOW()
            WHERE id = ${len(args) - 1} AND user_id = ${len(args)}
            RETURNING id, name, content, agent, created_at, updated_at
            """,
            *args,
        )
    finally:
        await connection.close()
    if row is None:
        return JSONResponse({"error": "Template not found"}, status_code=404)
    return JSONResponse(_template_json(row))


async def delete_template(request: Request) -> JSONResponse:
    user = await authenticated_user(request)
    if isinstance(user, JSONResponse):
        return user
    template_id = parse_uuid(request.path_params["template_id"])
    if template_id is None:
        return JSONResponse({"error": "Template not found"}, status_code=404)
    connection = await connect()
    try:
        result = await connection.execute(
            "DELETE FROM templates WHERE id = $1 AND user_id = $2",
            template_id,
            user["id"],
        )
    finally:
        await connection.close()
    if result == "DELETE 0":
        return JSONResponse({"error": "Template not found"}, status_code=404)
    return JSONResponse({"success": True, "message": "Template deleted successfully"})


def register_template_routes(mcp: FastMCP) -> None:
    mcp.custom_route("/api/templates", methods=["GET"])(list_templates)
    mcp.custom_route("/api/templates", methods=["POST"])(create_template)
    mcp.custom_route("/api/templates/{template_id}", methods=["GET"])(get_template)
    mcp.custom_route("/api/templates/{template_id}", methods=["PUT"])(update_template)
    mcp.custom_route("/api/templates/{template_id}", methods=["DELETE"])(
        delete_template
    )
