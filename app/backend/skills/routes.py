# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Authenticated HTTP routes for the canonical skill catalog."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from modules.common import authenticated_user, connect
from domain_packages.context import require_context
from domain_packages.files import resource_files
from skills.repository import get_skill, list_skills
from skills.serialization import serialize_hierarchy, serialize_skill


async def skill_list(request: Request) -> JSONResponse:
    user = await authenticated_user(request)
    if isinstance(user, JSONResponse):
        return user
    require_context(user["id"])
    connection = await connect()
    try:
        rows = await list_skills(
            connection,
            query=request.query_params.get("q", "").strip(),
        )
    finally:
        await connection.close()
    return JSONResponse(serialize_hierarchy(rows))


async def skill_detail(request: Request) -> JSONResponse:
    user = await authenticated_user(request)
    if isinstance(user, JSONResponse):
        return user
    require_context(user["id"])
    connection = await connect()
    try:
        row = await get_skill(connection, request.path_params["skill_id"])
        files = (
            await resource_files(connection, require_context(user["id"]), row["id"])
            if row
            else []
        )
    finally:
        await connection.close()
    if row is None:
        return JSONResponse({"error": "Skill not found"}, status_code=404)
    return JSONResponse({**serialize_skill(row), "files": files})


def register_skill_routes(mcp: FastMCP) -> None:
    mcp.custom_route("/api/skills", methods=["GET"])(skill_list)
    mcp.custom_route("/api/skills/{skill_id}", methods=["GET"])(skill_detail)
