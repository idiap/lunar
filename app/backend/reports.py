# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
import hashlib
import html
import json
import uuid
from datetime import datetime, timezone

import asyncpg
from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response

from auth import current_user
from config import DATABASE_URL, PUBLIC_BASE_URL
from state import STATE
from domain_packages.context import require_context
from modules.common import authenticated_user


def _digest(value: object) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def build_report(title: str, artifact: object, report_id: str) -> str:
    safe_title = html.escape(title)
    if isinstance(artifact, str):
        rendered = html.escape(artifact)
    else:
        rendered = html.escape(
            json.dumps(artifact, indent=2, sort_keys=True, ensure_ascii=False)
        )
    created_at = datetime.now(timezone.utc).strftime("%B %d, %Y at %H:%M UTC")
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Report</title>
  <style>
    :root {{ font-family: Inter, system-ui, sans-serif; color: #0d181c; background: #f4f6f9; }}
    body {{ margin: 0; padding: 48px 20px; }}
    article {{ max-width: 760px; margin: auto; padding: 48px; background: #fff; border: 1px solid #e4e8ee;
      border-radius: 14px; box-shadow: 0 16px 48px rgba(30, 50, 87, .08); }}
    .label {{ color: #4db1dd; font-size: 12px; font-weight: 700; letter-spacing: .12em; text-transform: uppercase; }}
    h1 {{ margin: 12px 0 32px; color: #1e3257; font-size: clamp(32px, 6vw, 56px); line-height: 1.05; }}
    pre {{ overflow-wrap: anywhere; white-space: pre-wrap; color: #334155; font: 15px/1.7 Inter, system-ui, sans-serif; }}
    footer {{ margin-top: 48px; padding-top: 20px; border-top: 1px solid #e4e8ee; color: #5b6b73; font-size: 13px; }}
  </style>
</head>
<body>
  <article>
    <div class="label">Quality-released report</div>
    <h1>{safe_title}</h1>
    <pre>{rendered}</pre>
    <footer>Created {created_at} · Report {report_id}</footer>
  </article>
</body>
</html>"""


async def _publish_released_artifact(
    release_result_id: str,
    title: str,
    principal: str,
) -> dict[str, str]:
    """Publish only an exact artifact released by the scientific quality gate."""
    release_result = STATE.get(release_result_id, "release_result")
    if not principal:
        raise PermissionError("A valid user MCP token is required")

    context = require_context(uuid.UUID(principal))
    title = title.strip()
    if not title:
        raise ValueError("title must not be empty")
    if (
        release_result.get("schema_version") != "mcp.evaluated-delivery/v1"
        or release_result.get("candidate_withheld") is not False
        or release_result.get("released_artifact") is None
        or release_result.get("presentable_as_user_answer") is not True
    ):
        raise ValueError("an exact released artifact is required for publication")
    artifact = release_result["released_artifact"]
    artifact_digest = _digest(artifact)
    decision = release_result.get("decision")
    if (
        not isinstance(decision, dict)
        or decision.get("decision") != "release"
        or decision.get("artifact_digest") != artifact_digest
    ):
        raise ValueError("release decision does not bind the released artifact")

    report_id = str(uuid.uuid4())
    report_html = build_report(title, artifact, report_id)
    connection = await asyncpg.connect(DATABASE_URL)
    try:
        await connection.execute(
            """
            INSERT INTO reports
                (id, query, html, user_id, artifact_digest, release_receipt, version_id)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
            uuid.UUID(report_id),
            title,
            report_html,
            uuid.UUID(principal),
            artifact_digest,
            json.dumps(release_result, sort_keys=True),
            context.version_id,
        )
    finally:
        await connection.close()

    return {
        "report_id": report_id,
        "url": f"{PUBLIC_BASE_URL}/api/reports/{report_id}?package_version_id={context.version_id}",
        "artifact_digest": artifact_digest,
    }


async def list_reports(request: Request) -> JSONResponse:
    user = await current_user(request)
    if user is None:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    context = require_context(user["id"])
    connection = await asyncpg.connect(DATABASE_URL)
    try:
        rows = await connection.fetch(
            "SELECT id, query, created_at FROM reports WHERE user_id = $1 AND version_id=$2 ORDER BY created_at DESC",
            user["id"],
            context.version_id,
        )
    finally:
        await connection.close()
    return JSONResponse(
        {
            "reports": [
                {
                    "id": str(row["id"]),
                    "query": row["query"],
                    "created_at": row["created_at"].isoformat(),
                    "url": f"{PUBLIC_BASE_URL}/api/reports/{row['id']}?package_version_id={context.version_id}",
                }
                for row in rows
            ]
        }
    )


async def get_report(request: Request) -> Response:
    user = await authenticated_user(request)
    if isinstance(user, JSONResponse):
        return user
    context = require_context(user["id"])
    try:
        report_id = uuid.UUID(request.path_params["report_id"])
    except ValueError:
        return HTMLResponse("Report not found", status_code=404)

    connection = await asyncpg.connect(DATABASE_URL)
    try:
        row = await connection.fetchrow(
            "SELECT html FROM reports WHERE id = $1 AND user_id=$2 AND version_id=$3",
            report_id,
            context.user_id,
            context.version_id,
        )
    finally:
        await connection.close()
    if row is None:
        return HTMLResponse("Report not found", status_code=404)
    return HTMLResponse(
        row["html"],
        headers={
            "Content-Security-Policy": "sandbox; default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'",
            "Cache-Control": "private, no-cache",
        },
    )


async def delete_report(request: Request) -> JSONResponse:
    user = await current_user(request)
    if user is None:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    try:
        report_id = uuid.UUID(request.path_params["report_id"])
    except ValueError:
        return JSONResponse({"error": "Report not found"}, status_code=404)

    context = require_context(user["id"])
    connection = await asyncpg.connect(DATABASE_URL)
    try:
        result = await connection.execute(
            "DELETE FROM reports WHERE id = $1 AND user_id = $2 AND version_id=$3",
            report_id,
            user["id"],
            context.version_id,
        )
    finally:
        await connection.close()
    if result == "DELETE 0":
        return JSONResponse({"error": "Report not found"}, status_code=404)
    return JSONResponse({"ok": True})


def register_report_routes(mcp: FastMCP) -> None:
    mcp.custom_route("/api/reports", methods=["GET"])(list_reports)
    mcp.custom_route("/api/reports/{report_id}", methods=["GET"])(get_report)
    mcp.custom_route("/api/reports/{report_id}", methods=["DELETE"])(delete_report)
