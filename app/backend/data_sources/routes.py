# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""HTTP registration for the data-source catalog."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from data_sources.repository import get_source, list_sources
from data_sources.serialization import serialize_source
from modules.common import authenticated_user, connect, json_value
from domain_packages.context import require_context
from domain_packages.files import resource_files


def _pagination(request: Request) -> tuple[int, int] | JSONResponse:
    try:
        page = int(request.query_params.get("page", "1"))
        page_size = int(request.query_params.get("page_size", "20"))
    except ValueError:
        return JSONResponse(
            {"error": "page and page_size must be integers"}, status_code=400
        )
    if page < 1 or page_size < 1 or page_size > 100:
        return JSONResponse(
            {
                "error": "page must be at least 1 and page_size must be between 1 and 100"
            },
            status_code=400,
        )
    return page, page_size


async def data_source_list(request: Request) -> JSONResponse:
    user = await authenticated_user(request)
    if isinstance(user, JSONResponse):
        return user
    pagination = _pagination(request)
    if isinstance(pagination, JSONResponse):
        return pagination
    page, page_size = pagination
    require_context(user["id"])
    connection = await connect()
    try:
        rows, total = await list_sources(
            connection,
            query=request.query_params.get("q", "").strip(),
            page=page,
            page_size=page_size,
        )
    finally:
        await connection.close()
    total_pages = (total + page_size - 1) // page_size
    return JSONResponse(
        {
            "items": [serialize_source(row) for row in rows],
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": total_pages,
        }
    )


async def data_source_detail(request: Request) -> JSONResponse:
    user = await authenticated_user(request)
    if isinstance(user, JSONResponse):
        return user
    require_context(user["id"])
    connection = await connect()
    try:
        row = await get_source(connection, request.path_params["resource_id"])
        context = require_context(user["id"])
        files = await resource_files(connection, context, row["id"]) if row else []
        workflows = (
            await connection.fetch(
                "SELECT registration FROM package_workflows WHERE version_id=$1 AND user_id=$2 AND registration ? 'entry_file'",
                context.version_id,
                context.user_id,
            )
            if row
            else []
        )
    finally:
        await connection.close()
    if row is None:
        return JSONResponse({"error": "Data source not found"}, status_code=404)
    result = serialize_source(row, detail=True)
    result["files"] = files
    by_path = {item["path"]: item for item in files}
    result["local_files"] = [
        {
            **item,
            "file_id": by_path[item["file"]]["id"],
            "url": by_path[item["file"]]["url"],
        }
        for item in result["local_files"]
        if item["file"] in by_path
    ]
    dataset_workflows = {
        identity
        for dataset in result["datasets"]
        for identity in dataset.get("workflow_ids", [])
    }
    for record in workflows:
        registration = json_value(record["registration"])
        bindings = registration.get("metadata", {}).get("source_bindings", [])
        if registration["id"] in dataset_workflows or any(
            item.get("resource_id") == result["resource_id"] for item in bindings
        ):
            result["workflows"].append(
                {"id": registration["id"], "name": registration["name"]}
            )
    return JSONResponse(result)


def register_data_source_routes(mcp: FastMCP) -> None:
    mcp.custom_route("/api/data-sources", methods=["GET"])(data_source_list)
    mcp.custom_route("/api/data-sources/{resource_id}", methods=["GET"])(
        data_source_detail
    )
