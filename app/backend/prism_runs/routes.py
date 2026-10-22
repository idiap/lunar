# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""HTTP registration for Prism workflow runs."""

from __future__ import annotations

import hashlib
import uuid

from mcp.server.fastmcp import FastMCP
from pydantic import ValidationError
from starlette.requests import Request
from starlette.responses import (
    JSONResponse,
    Response,
    StreamingResponse,
    RedirectResponse,
)

from modules.common import authenticated_user, connect, request_model
from domain_packages.context import require_context
from domain_packages.routes import configured_storage
from prism_runs.repository import (
    delete_run,
    get_artifact,
    get_run,
    list_runs,
    run_relations,
)
from prism_runs.schemas import PrismRunRequest, RunListQuery, ReasoningSubscription
from prism_runs.serialization import serialize_run
from prism_runs.service import (
    AIModelNotFoundError,
    RunUnavailableError,
    accept_run,
    delete_run_artifacts,
    public_workflows,
    stop_run,
)


async def workflow_list(request: Request) -> JSONResponse:
    user = await authenticated_user(request)
    if isinstance(user, JSONResponse):
        return user
    require_context(user["id"])
    return JSONResponse(await public_workflows())


async def create_prism_run(request: Request) -> JSONResponse:
    user = await authenticated_user(request)
    if isinstance(user, JSONResponse):
        return user
    workflow_id = request.path_params["workflow_id"]
    body = await request_model(request, PrismRunRequest)
    if isinstance(body, JSONResponse):
        return body
    try:
        run_id, digest = await accept_run(
            user_id=user["id"], workflow_id=workflow_id, request=body
        )
    except KeyError:
        return JSONResponse({"error": "Prism workflow not found"}, status_code=404)
    except AIModelNotFoundError:
        return JSONResponse({"error": "AI model not found"}, status_code=404)
    except ValidationError as exc:
        return JSONResponse(
            {"error": "Invalid workflow inputs", "details": exc.errors()},
            status_code=422,
        )
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=422)
    except (PermissionError, RunUnavailableError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=409)
    return JSONResponse(
        {"run_id": str(run_id), "state": "queued", "accepted_request_digest": digest},
        status_code=202,
    )


def _list_query(request: Request) -> RunListQuery | JSONResponse:
    try:
        return RunListQuery.model_validate(
            {
                key: value
                for key, value in request.query_params.items()
                if key != "package_version_id"
            }
        )
    except ValidationError as exc:
        return JSONResponse(
            {"error": "Invalid pagination", "details": exc.errors()}, status_code=400
        )


async def prism_run_list(request: Request) -> JSONResponse:
    user = await authenticated_user(request)
    if isinstance(user, JSONResponse):
        return user
    query = _list_query(request)
    if isinstance(query, JSONResponse):
        return query
    connection = await connect()
    try:
        rows, total = await list_runs(
            connection,
            user_id=user["id"],
            workflow_id=query.workflow_id,
            page=query.page,
            page_size=query.page_size,
        )
    finally:
        await connection.close()
    return JSONResponse(
        {
            "items": [serialize_run(row) for row in rows],
            "page": query.page,
            "page_size": query.page_size,
            "total": total,
            "total_pages": (total + query.page_size - 1) // query.page_size,
        }
    )


async def prism_run_detail(request: Request) -> JSONResponse:
    user = await authenticated_user(request)
    if isinstance(user, JSONResponse):
        return user
    try:
        run_id = uuid.UUID(request.path_params["run_id"])
    except ValueError:
        return JSONResponse({"error": "Prism run not found"}, status_code=404)
    connection = await connect()
    try:
        row = await get_run(connection, run_id=run_id, user_id=user["id"])
        if row is None:
            return JSONResponse({"error": "Prism run not found"}, status_code=404)
        relations = await run_relations(connection, run_id)
    finally:
        await connection.close()
    return JSONResponse(serialize_run(row, relations))


async def prism_run_artifact(request: Request) -> Response:
    """Serve a digest-bound artifact from an owned run's confined directory."""

    user = await authenticated_user(request)
    if isinstance(user, JSONResponse):
        return user
    try:
        run_id = uuid.UUID(request.path_params["run_id"])
        artifact_id = uuid.UUID(request.path_params["artifact_id"])
    except ValueError:
        return JSONResponse({"error": "Prism artifact not found"}, status_code=404)
    connection = await connect()
    try:
        artifact = await get_artifact(
            connection,
            run_id=run_id,
            artifact_id=artifact_id,
            user_id=user["id"],
        )
    finally:
        await connection.close()
    if artifact is None:
        return JSONResponse({"error": "Prism artifact not found"}, status_code=404)

    context = require_context(user["id"])
    if artifact["imported"] and str(artifact["safe_locator"]).startswith("package:"):
        from domain_packages.files import file_url

        return RedirectResponse(
            file_url(
                context,
                uuid.UUID(str(artifact["safe_locator"]).removeprefix("package:")),
            )
        )
    try:
        storage = configured_storage()
        root = storage.run_root(context, run_id)
        if artifact["imported"] or str(root) != artifact["artifact_root"]:
            return JSONResponse({"error": "Artifact file unavailable"}, status_code=410)
        path = storage.run_file(context, run_id, str(artifact["safe_locator"]))
        content = path.read_bytes()
    except (ValueError, OSError):
        return JSONResponse({"error": "Artifact file unavailable"}, status_code=410)
    digest = "sha256:" + hashlib.sha256(content).hexdigest()
    if digest != artifact["content_digest"]:
        return JSONResponse(
            {"error": "Artifact integrity check failed"}, status_code=409
        )
    return Response(
        content,
        media_type=artifact["media_type"],
        headers={
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-cache",
            "Content-Security-Policy": "sandbox; default-src 'none'",
        },
    )


async def prism_run_delete(request: Request) -> JSONResponse:
    user = await authenticated_user(request)
    if isinstance(user, JSONResponse):
        return user
    try:
        run_id = uuid.UUID(request.path_params["run_id"])
    except ValueError:
        return JSONResponse({"error": "Prism run not found"}, status_code=404)
    connection = await connect()
    try:
        row = await get_run(connection, run_id=run_id, user_id=user["id"])
        if row is None:
            return JSONResponse({"error": "Prism run not found"}, status_code=404)
        if row["state"] not in {"completed", "failed", "cancelled"}:
            return JSONResponse(
                {"error": "A queued or running Prism run cannot be deleted"},
                status_code=409,
            )
        delete_run_artifacts(run_id=run_id, workflow_id=row["workflow_id"])
        if not await delete_run(connection, run_id=run_id, user_id=user["id"]):
            return JSONResponse({"error": "Prism run not found"}, status_code=404)
    finally:
        await connection.close()
    return JSONResponse({"success": True, "message": "Prism run deleted successfully"})


async def prism_run_stop(request: Request) -> JSONResponse:
    user = await authenticated_user(request)
    if isinstance(user, JSONResponse):
        return user
    try:
        run_id = uuid.UUID(request.path_params["run_id"])
    except ValueError:
        return JSONResponse({"error": "Prism run not found"}, status_code=404)
    connection = await connect()
    try:
        row = await get_run(connection, run_id=run_id, user_id=user["id"])
    finally:
        await connection.close()
    if row is None:
        return JSONResponse({"error": "Prism run not found"}, status_code=404)
    if row["state"] not in {"queued", "running"}:
        return JSONResponse({"error": "Prism run is no longer active"}, status_code=409)
    if not stop_run(run_id):
        return JSONResponse(
            {"error": "The active worker is unavailable on this server"},
            status_code=409,
        )
    return JSONResponse({"run_id": str(run_id), "state": "stopping"}, status_code=202)


async def prism_reasoning_stream(request: Request) -> Response:
    user = await authenticated_user(request)
    if isinstance(user, JSONResponse):
        return user
    try:
        parameters: dict[str, str | list[str]] = {
            key: value
            for key, value in request.query_params.items()
            if key != "package_version_id"
        }
        run_ids = parameters.get("run_ids", "")
        parameters["run_ids"] = (
            run_ids.split(",") if isinstance(run_ids, str) else run_ids
        )
        query = ReasoningSubscription.model_validate(parameters)
        if len(set(query.run_ids)) != len(query.run_ids):
            raise ValueError("duplicate run IDs")
    except (ValidationError, ValueError):
        return JSONResponse(
            {"error": "Invalid reasoning subscription"}, status_code=400
        )
    connection = await connect()
    try:
        for run_id in query.run_ids:
            row = await get_run(connection, run_id=run_id, user_id=user["id"])
            if row is None or row["workflow_id"] != query.workflow_id:
                return JSONResponse({"error": "Prism run not found"}, status_code=404)
    finally:
        await connection.close()
    from prism_runs.reasoning_stream import reasoning_snapshots

    return StreamingResponse(
        reasoning_snapshots(user_id=user["id"], **query.model_dump()),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def register_prism_run_routes(mcp: FastMCP) -> None:
    mcp.custom_route("/api/prism/workflows", methods=["GET"])(workflow_list)
    mcp.custom_route("/api/prism/workflows/{workflow_id}/runs", methods=["POST"])(
        create_prism_run
    )
    mcp.custom_route("/api/prism/runs", methods=["GET"])(prism_run_list)
    mcp.custom_route("/api/prism/runs/reasoning", methods=["GET"])(
        prism_reasoning_stream
    )
    mcp.custom_route("/api/prism/runs/{run_id}", methods=["GET"])(prism_run_detail)
    mcp.custom_route("/api/prism/runs/{run_id}/stop", methods=["POST"])(prism_run_stop)
    mcp.custom_route(
        "/api/prism/runs/{run_id}/artifacts/{artifact_id}", methods=["GET"]
    )(prism_run_artifact)
    mcp.custom_route("/api/prism/runs/{run_id}", methods=["DELETE"])(prism_run_delete)
