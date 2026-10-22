# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""HTTP registration for stored provenance exports."""

from __future__ import annotations

import uuid

from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from modules.common import authenticated_user, connect, json_value, record_json
from provenance.repository import get_export
from provenance.service import graph_view_model


async def run_provenance(request: Request) -> Response:
    user = await authenticated_user(request)
    if isinstance(user, JSONResponse):
        return user
    try:
        run_id = uuid.UUID(request.path_params["run_id"])
    except ValueError:
        return JSONResponse(
            {"error": "Prism run provenance not found"}, status_code=404
        )
    requested = request.query_params.get("format")
    if requested not in {None, "prov-json", "json-ld"}:
        return JSONResponse(
            {"error": "format must be prov-json or json-ld"}, status_code=400
        )
    output_format = requested or "prov-json"
    section_id = request.query_params.get("section")
    typed = None
    connection = await connect()
    try:
        row = await get_export(
            connection,
            run_id=run_id,
            user_id=user["id"],
            output_format=output_format,
        )
        if row is not None and section_id:
            from domain_packages.context import require_context

            context = require_context(user["id"])
            outputs = await connection.fetch(
                "SELECT structured_value FROM prism_run_outputs WHERE run_id=$1 AND user_id=$2 AND version_id=$3",
                run_id,
                user["id"],
                context.version_id,
            )
            typed = next(
                (
                    (json_value(output["structured_value"], {}) or {}).get(
                        "typed_report"
                    )
                    for output in outputs
                    if (json_value(output["structured_value"], {}) or {}).get(
                        "typed_report"
                    )
                ),
                None,
            )
    finally:
        await connection.close()
    if row is None:
        return JSONResponse(
            {"error": "Prism run provenance not found"}, status_code=404
        )
    value = record_json(row)
    document = json_value(value["document"], {})
    if section_id:
        if typed is None or section_id not in typed["sections"]:
            return JSONResponse({"error": "Report section not found"}, status_code=404)
        from reporting.service import slice_prov_document

        if requested is None:
            document = slice_prov_document(
                document, typed["sections"][section_id]["entity"]
            )
    if requested is not None:
        return JSONResponse(
            {
                "format": value["format"],
                "media_type": value["media_type"],
                "document": document,
                "digest": value["wrapper_digest"],
                "generated_at": value["generated_at"],
            }
        )
    return JSONResponse(
        {
            "run_id": str(run_id),
            "native_reference": (
                typed["sections"][section_id]["reference"] if typed else None
            ),
            "recorded_execution": typed["native"]["run_id"] if typed else None,
            "export": {
                "format": value["format"],
                "media_type": value["media_type"],
                "digest": value["wrapper_digest"],
                "generated_at": value["generated_at"],
            },
            "graph": graph_view_model(document),
        }
    )


def register_provenance_routes(mcp: FastMCP) -> None:
    mcp.custom_route("/api/prism/runs/{run_id}/provenance", methods=["GET"])(
        run_provenance
    )
