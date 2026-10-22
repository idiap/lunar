# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""HTTP registration for template execution and report lineage."""

from __future__ import annotations

import uuid

from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from modules.common import (
    authenticated_user,
    connect,
    json_value,
    record_json,
    request_model,
)
from provenance.service import graph_view_model
from reporting.repository import (
    available_outputs,
    report_export,
    report_lineage,
    report_sections,
    template_for_user,
)
from reporting.schemas import TemplateRunRequest
from reporting.service import (
    BindingConflictError,
    BindingValidationError,
    TemplateNotFoundError,
    execute_template,
    parse_template,
    slice_prov_document,
)


def _uuid(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


async def template_outputs(request: Request) -> JSONResponse:
    user = await authenticated_user(request)
    if isinstance(user, JSONResponse):
        return user
    template_id = _uuid(request.path_params["template_id"])
    if template_id is None:
        return JSONResponse({"error": "Template not found"}, status_code=404)
    connection = await connect()
    try:
        template = await template_for_user(connection, template_id, user["id"])
        if template is None:
            return JSONResponse({"error": "Template not found"}, status_code=404)
        inventory = parse_template(template["content"])
        rows = await available_outputs(connection, user["id"], inventory["variables"])
    finally:
        await connection.close()
    return JSONResponse(
        {
            "variables": inventory["variables"],
            "items": [record_json(row) for row in rows],
        }
    )


async def run_template(request: Request) -> JSONResponse:
    user = await authenticated_user(request)
    if isinstance(user, JSONResponse):
        return user
    template_id = _uuid(request.path_params["template_id"])
    if template_id is None:
        return JSONResponse({"error": "Template not found"}, status_code=404)
    body = await request_model(request, TemplateRunRequest)
    if isinstance(body, JSONResponse):
        return body
    connection = await connect()
    try:
        try:
            report_id = await execute_template(
                connection,
                template_id=template_id,
                user_id=user["id"],
                report_name=body.report_name,
                supplied_bindings=body.bindings,
            )
        except TemplateNotFoundError:
            return JSONResponse({"error": "Template not found"}, status_code=404)
        except BindingValidationError as exc:
            return JSONResponse(
                {"error": str(exc), "details": exc.details}, status_code=422
            )
        except BindingConflictError as exc:
            return JSONResponse({"error": str(exc)}, status_code=409)
    finally:
        await connection.close()
    return JSONResponse({"report_id": str(report_id)}, status_code=201)


async def generated_report_provenance(request: Request) -> JSONResponse:
    user = await authenticated_user(request)
    if isinstance(user, JSONResponse):
        return user
    report_id = _uuid(request.path_params["report_id"])
    if report_id is None:
        return JSONResponse({"error": "Report not found"}, status_code=404)
    requested = request.query_params.get("format")
    if requested not in {None, "prov-json", "json-ld"}:
        return JSONResponse(
            {"error": "format must be prov-json or json-ld"}, status_code=400
        )
    connection = await connect()
    try:
        lineage = await report_lineage(connection, report_id, user["id"])
        if lineage is None:
            return JSONResponse({"error": "Report not found"}, status_code=404)
        if lineage["generation_type"] != "template" and not lineage["imported"]:
            return JSONResponse(
                {"status": "provenance_unavailable", "reason": "manual_report"}
            )
        export = await report_export(connection, report_id, requested or "prov-json")
        sections = await report_sections(connection, report_id)
    finally:
        await connection.close()
    if export is None:
        return JSONResponse(
            {"status": "provenance_unavailable", "reason": "export_missing"},
            status_code=409,
        )
    value = record_json(export)
    document = json_value(value["document"], {})
    if requested:
        return JSONResponse(
            {
                "format": value["format"],
                "media_type": value["media_type"],
                "document": document,
                "digest": value["wrapper_digest"],
                "generated_at": value["generated_at"],
            }
        )
    metadata = record_json(lineage)
    return JSONResponse(
        {
            "status": "available",
            "report": metadata,
            "export": {
                "format": value["format"],
                "media_type": value["media_type"],
                "digest": value["wrapper_digest"],
            },
            "sections": [record_json(row) for row in sections],
            "graph": graph_view_model(document),
        }
    )


async def report_section_provenance(request: Request) -> JSONResponse:
    user = await authenticated_user(request)
    if isinstance(user, JSONResponse):
        return user
    report_id = _uuid(request.path_params["report_id"])
    if report_id is None:
        return JSONResponse({"error": "Report not found"}, status_code=404)
    section_id = request.path_params["section_id"]
    connection = await connect()
    try:
        lineage = await report_lineage(connection, report_id, user["id"])
        if lineage is None:
            return JSONResponse({"error": "Report not found"}, status_code=404)
        sections = await report_sections(connection, report_id)
        section = next(
            (row for row in sections if row["section_id"] == section_id), None
        )
        if section is None:
            return JSONResponse({"error": "Report section not found"}, status_code=404)
        export = await report_export(connection, report_id, "prov-json")
    finally:
        await connection.close()
    if export is None:
        return JSONResponse(
            {"status": "provenance_unavailable", "reason": "export_missing"},
            status_code=409,
        )
    document = slice_prov_document(
        json_value(export["document"], {}), section["provenance_entity_id"]
    )
    source_summary = [
        {"id": node["id"], "label": node["label"], "type": node["type"]}
        for node in graph_view_model(document)["nodes"]
        if node["type"] in {"CatalogDataSource", "ConsumedDataSource", "InputEntity"}
    ]
    metadata = json_value(lineage["provenance_data"], {})
    typed = metadata.get("original_metadata", {}).get("typed_report")
    native = typed["sections"][section_id]["reference"] if typed else None
    return JSONResponse(
        {
            "status": "available",
            "report": record_json(lineage),
            "section": record_json(section),
            "native_reference": native,
            "recorded_execution": typed["native"]["run_id"] if typed else None,
            "source_summary": source_summary,
            "graph": graph_view_model(document),
        }
    )


def register_reporting_routes(mcp: FastMCP) -> None:
    mcp.custom_route("/api/templates/{template_id}/outputs", methods=["GET"])(
        template_outputs
    )
    mcp.custom_route("/api/templates/{template_id}/runs", methods=["POST"])(
        run_template
    )
    mcp.custom_route("/api/report/{report_id}/provenance", methods=["GET"])(
        generated_report_provenance
    )
    mcp.custom_route(
        "/api/report/{report_id}/sections/{section_id}/provenance", methods=["GET"]
    )(report_section_provenance)
