# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Version-scoped report CRUD with durable imported and edited revision history."""

import json
import uuid

from starlette.responses import JSONResponse
from domain_packages.context import require_context
from domain_packages.files import resource_files
from modules.common import (
    authenticated_user,
    connect,
    json_value,
    parse_uuid,
    record_json,
    request_model,
)
from modules.schemas import ReportInput, ReportUpdate
from reports import build_report

REPORT_COLUMNS = """id,COALESCE(name,query) AS name,COALESCE(content,html) AS content,
    created_at,version,version_id,provenance_data,content_type_id,template_id,
    template_content_digest,generation_status,generation_type,generated_at,imported"""


def _report_json(row):
    result = record_json(row)
    result["provenance_data"] = json_value(result.get("provenance_data"))
    result["content_type"] = None
    result.pop("user_id", None)
    return result


async def create_report(request):
    user = await authenticated_user(request)
    if isinstance(user, JSONResponse):
        return user
    context = require_context(user["id"])
    body = await request_model(request, ReportInput)
    if isinstance(body, JSONResponse):
        return body
    identity = uuid.uuid4()
    connection = await connect()
    try:
        row = await connection.fetchrow(
            f"""INSERT INTO reports
            (id,query,html,user_id,version_id,name,content,version,content_type_id)
            VALUES($1,$2,$3,$4,$5,$2,$6,1,$7) RETURNING {REPORT_COLUMNS}""",
            identity,
            body.name.strip(),
            build_report(body.name.strip(), body.content, str(identity)),
            context.user_id,
            context.version_id,
            body.content,
            body.content_type_id,
        )
    finally:
        await connection.close()
    return JSONResponse(_report_json(row), status_code=201)


async def list_reports(request):
    user = await authenticated_user(request)
    if isinstance(user, JSONResponse):
        return user
    context = require_context(user["id"])
    try:
        raw = request.query_params.get("limit", "100")
        limit = None if raw.lower() == "none" else min(max(int(raw), 1), 500)
    except ValueError:
        return JSONResponse({"error": "Invalid report limit"}, status_code=400)
    connection = await connect()
    try:
        query = f"""SELECT {REPORT_COLUMNS},NULL::uuid AS run_id,NULL::text AS workflow_id,NULL::text AS mode
            FROM reports WHERE user_id=$1 AND version_id=$2
            UNION ALL
            SELECT outputs.id,INITCAP(REPLACE(runs.workflow_id,'-',' ')) || ' report',
                outputs.markdown,outputs.created_at,1,runs.version_id,NULL::jsonb,NULL::integer,NULL::uuid,
                NULL::text,runs.state,'prism',outputs.created_at,runs.imported,runs.id,runs.workflow_id,runs.mode
            FROM prism_run_outputs outputs JOIN prism_runs runs ON runs.id=outputs.run_id
                AND runs.version_id=outputs.version_id AND runs.user_id=outputs.user_id
            WHERE runs.user_id=$1 AND runs.version_id=$2 AND NULLIF(BTRIM(outputs.markdown),'') IS NOT NULL
            ORDER BY created_at DESC,id DESC"""
        rows = (
            await connection.fetch(query, context.user_id, context.version_id)
            if limit is None
            else await connection.fetch(
                query + " LIMIT $3", context.user_id, context.version_id, limit
            )
        )
    finally:
        await connection.close()
    return JSONResponse([_report_json(row) for row in rows])


async def get_report(request):
    user = await authenticated_user(request)
    if isinstance(user, JSONResponse):
        return user
    context = require_context(user["id"])
    identity = parse_uuid(request.path_params["report_id"])
    if identity is None:
        return JSONResponse({"error": "Report not found"}, status_code=404)
    try:
        requested = (
            int(request.query_params["version"])
            if "version" in request.query_params
            else None
        )
        if requested is not None and requested < 1:
            raise ValueError
    except ValueError:
        return JSONResponse({"error": "Invalid report revision"}, status_code=400)
    connection = await connect()
    try:
        row = await connection.fetchrow(
            f"SELECT {REPORT_COLUMNS} FROM reports WHERE id=$1 AND user_id=$2 AND version_id=$3",
            identity,
            context.user_id,
            context.version_id,
        )
        if row is None:
            return JSONResponse({"error": "Report not found"}, status_code=404)
        result = _report_json(row)
        revisions = await connection.fetch(
            "SELECT revision,content,metadata FROM report_revisions WHERE report_id=$1 AND user_id=$2 AND version_id=$3 ORDER BY revision",
            identity,
            context.user_id,
            context.version_id,
        )
        result["revisions"] = [
            {
                "version": item["revision"],
                "content": item["content"],
                "metadata": json_value(item["metadata"], {}),
            }
            for item in revisions
        ]
        if requested is not None and requested != row["version"]:
            historical = next(
                (item for item in result["revisions"] if item["version"] == requested),
                None,
            )
            if historical is None:
                return JSONResponse(
                    {"error": "Report version not found"}, status_code=404
                )
            result.update(content=historical["content"], version=requested)
        sections = await connection.fetch(
            """SELECT section_id,ordinal,placeholder_name,run_output_id,rendered_markdown,content_digest,provenance_entity_id
            FROM report_sections WHERE report_id=$1 AND user_id=$2 AND version_id=$3 ORDER BY ordinal,id""",
            identity,
            context.user_id,
            context.version_id,
        )
        result["sections"] = [record_json(item) for item in sections]
        if row["template_id"]:
            result["template_name"] = await connection.fetchval(
                "SELECT name FROM templates WHERE id=$1 AND user_id=$2",
                row["template_id"],
                context.user_id,
            )
        document = await connection.fetchval(
            "SELECT document FROM package_resources WHERE id=$1 AND user_id=$2 AND version_id=$3 AND collection='reports'",
            identity,
            context.user_id,
            context.version_id,
        )
        files = await resource_files(connection, context, identity)
        original = json_value(document, {})
        result["typed_report"] = original.get("metadata", {}).get("typed_report")
        result["template_snapshot"] = original.get("template_snapshot")
        result["read_only"] = (
            result["typed_report"] is not None
            or row["generation_type"] == "template"
            or json_value(document, {}).get("metadata", {}).get("generation_type")
            == "prism"
        )
        result["files"] = files
        by_path = {item["path"]: item for item in files}
        result["attachments"] = [
            {
                **item,
                "file_id": by_path[item["file"]]["id"],
                "url": by_path[item["file"]]["url"],
                "media_type": by_path[item["file"]]["media_type"],
            }
            for item in json_value(document, {}).get("attachments", [])
            if item["file"] in by_path
        ]
    finally:
        await connection.close()
    return JSONResponse(result)


async def update_report(request):
    user = await authenticated_user(request)
    if isinstance(user, JSONResponse):
        return user
    context = require_context(user["id"])
    identity = parse_uuid(request.path_params["report_id"])
    if identity is None:
        return JSONResponse({"error": "Report not found"}, status_code=404)
    body = await request_model(request, ReportUpdate)
    if isinstance(body, JSONResponse):
        return body
    values = body.model_dump(exclude_unset=True, exclude_none=True)
    if "versions" in values.get("provenance_data", {}):
        return JSONResponse(
            {"error": "Report revision history is server-managed"}, status_code=422
        )
    connection = await connect()
    try:
        async with connection.transaction():
            current = await connection.fetchrow(
                f"SELECT {REPORT_COLUMNS} FROM reports WHERE id=$1 AND user_id=$2 AND version_id=$3 FOR UPDATE",
                identity,
                context.user_id,
                context.version_id,
            )
            if current is None:
                return JSONResponse({"error": "Report not found"}, status_code=404)
            document = await connection.fetchval(
                "SELECT document FROM package_resources WHERE id=$1 AND user_id=$2 AND version_id=$3 AND collection='reports'",
                identity,
                context.user_id,
                context.version_id,
            )
            if (
                "typed_report" in json_value(document, {}).get("metadata", {})
                or current["generation_type"] == "template"
                or json_value(document, {}).get("metadata", {}).get("generation_type")
                == "prism"
            ):
                return JSONResponse(
                    {"error": "Generated reports are immutable"}, status_code=409
                )
            name = values.get("name", current["name"])
            if not name.strip():
                return JSONResponse(
                    {"error": "Report name must not be empty"}, status_code=422
                )
            content = values.get("content", current["content"])
            changed = content != current["content"]
            revision = current["version"] + int(changed)
            provenance = json_value(current["provenance_data"], {})
            if changed:
                await connection.execute(
                    """INSERT INTO report_revisions(report_id,user_id,version_id,revision,content,metadata)
                    VALUES($1,$2,$3,$4,$5,$6::jsonb)""",
                    identity,
                    context.user_id,
                    context.version_id,
                    current["version"],
                    current["content"],
                    json.dumps({"provenance_data": provenance}),
                )
            provenance.update(values.get("provenance_data", {}))
            row = await connection.fetchrow(
                f"""UPDATE reports SET query=$1,name=$1,content=$2,html=$3,version=$4,
                provenance_data=$5::jsonb,content_type_id=COALESCE($6,content_type_id)
                WHERE id=$7 AND user_id=$8 AND version_id=$9 RETURNING {REPORT_COLUMNS}""",
                name,
                content,
                build_report(name, content, str(identity)),
                revision,
                json.dumps(provenance),
                values.get("content_type_id"),
                identity,
                context.user_id,
                context.version_id,
            )
    finally:
        await connection.close()
    return JSONResponse(_report_json(row))


async def report_provenance(request):
    response = await get_report(request)
    if response.status_code != 200:
        return response
    report = json.loads(bytes(response.body))
    return JSONResponse(
        {**(report.get("provenance_data") or {}), "versions": report["revisions"]}
    )


async def delete_report(request):
    user = await authenticated_user(request)
    if isinstance(user, JSONResponse):
        return user
    context = require_context(user["id"])
    identity = parse_uuid(request.path_params["report_id"])
    if identity is None:
        return JSONResponse({"error": "Report not found"}, status_code=404)
    connection = await connect()
    try:
        result = await connection.execute(
            "DELETE FROM reports WHERE id=$1 AND user_id=$2 AND version_id=$3",
            identity,
            context.user_id,
            context.version_id,
        )
    finally:
        await connection.close()
    if result == "DELETE 0":
        return JSONResponse({"error": "Report not found"}, status_code=404)
    return JSONResponse({"success": True, "message": "Report deleted successfully"})


def register_management_report_routes(mcp):
    for path, methods, handler in [
        ("/api/report", ["GET"], list_reports),
        ("/api/report", ["POST"], create_report),
        ("/api/report/{report_id}", ["GET"], get_report),
        ("/api/report/{report_id}", ["PUT"], update_report),
        ("/api/report/{report_id}", ["DELETE"], delete_report),
    ]:
        mcp.custom_route(path, methods=methods)(handler)
