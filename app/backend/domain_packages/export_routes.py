# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Authenticated ZIP download; leased temporary bytes live only for the response."""

import asyncio
from datetime import datetime
import hashlib
from uuid import UUID, uuid4

from starlette.responses import FileResponse, JSONResponse
from modules import common
from modules.common import authenticated_user, connect
from .archive_builder import ExportError
from .context import VersionNotFound
from .exporter import export_version
from .format.contract import PackageValidationError
from .routes import configured_storage
from .workflow_exporter import WorkflowNotFound, export_workflow
from .workspace import upload_workspace


class ExportResponse(FileResponse):
    def __init__(self, *args, workspace, **kwargs):
        super().__init__(*args, **kwargs)
        self.workspace = workspace

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            self.workspace.__exit__(None, None, None)


def file_digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


async def export_package(request):
    owner = await authenticated_user(request)
    if isinstance(owner, JSONResponse):
        return owner
    if request.query_params:
        return JSONResponse(
            {"error": "Export accepts no ownership overrides"}, status_code=400
        )
    try:
        identity = UUID(request.path_params["version_id"])
    except ValueError:
        return JSONResponse({"error": "Package version not found"}, status_code=404)
    storage = configured_storage()
    workspace = upload_workspace(storage, database_url=common.DATABASE_URL)
    directory = workspace.__enter__()
    connection = None
    try:
        connection = await connect()
        path, receipt = await export_version(
            connection,
            storage,
            user_id=owner["id"],
            version_id=identity,
            workspace=directory,
        )
        digest = await asyncio.to_thread(file_digest, path)
        export_id = uuid4()
        await connection.execute(
            """INSERT INTO package_exports(id,user_id,version_id,archive_digest,source_archive_digest,snapshot_at)
            VALUES($1,$2,$3,$4,$5,$6)""",
            export_id,
            owner["id"],
            identity,
            digest,
            receipt["source_archive_digest"],
            datetime.fromisoformat(receipt["snapshot_at"]),
        )
        return ExportResponse(
            path,
            workspace=workspace,
            media_type="application/zip",
            filename=f"{receipt['package_key']}-v{receipt['version']}.zip",
            headers={
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
                "ETag": '"' + digest + '"',
                "X-Lunar-Export-Id": str(export_id),
                "X-Lunar-Snapshot-At": receipt["snapshot_at"],
            },
        )
    except VersionNotFound:
        workspace.__exit__(None, None, None)
        return JSONResponse({"error": "Package version not found"}, status_code=404)
    except (ExportError, PackageValidationError, ValueError, OSError):
        workspace.__exit__(None, None, None)
        return JSONResponse(
            {
                "error": "Package export failed integrity validation; no archive published"
            },
            status_code=409,
        )
    except BaseException:
        workspace.__exit__(None, None, None)
        raise
    finally:
        if connection is not None:
            await connection.close()


async def export_workflow_package(request):
    """Download one workflow view, its source closure, and observed provenance."""

    owner = await authenticated_user(request)
    if isinstance(owner, JSONResponse):
        return owner
    if request.query_params:
        return JSONResponse(
            {"error": "Workflow export accepts no ownership overrides"},
            status_code=400,
        )
    try:
        identity = UUID(request.path_params["version_id"])
    except ValueError:
        return JSONResponse({"error": "Package version not found"}, status_code=404)
    workflow_id = request.path_params["workflow_id"]
    storage = configured_storage()
    workspace = upload_workspace(storage, database_url=common.DATABASE_URL)
    directory = workspace.__enter__()
    connection = None
    try:
        connection = await connect()
        path, receipt = await export_workflow(
            connection,
            storage,
            user_id=owner["id"],
            version_id=identity,
            workflow_id=workflow_id,
            workspace=directory,
        )
        archive_digest = await asyncio.to_thread(file_digest, path)
        export_id = uuid4()
        await connection.execute(
            """INSERT INTO package_exports(id,user_id,version_id,archive_digest,source_archive_digest,snapshot_at)
            VALUES($1,$2,$3,$4,$5,$6)""",
            export_id,
            owner["id"],
            identity,
            archive_digest,
            receipt["source_archive_digest"],
            datetime.fromisoformat(receipt["snapshot_at"]),
        )
        return ExportResponse(
            path,
            workspace=workspace,
            media_type="application/zip",
            filename=(
                f"{receipt['package_key']}-{receipt['workflow_name']}"
                f"-v{receipt['version']}.zip"
            ),
            headers={
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
                "ETag": '"' + archive_digest + '"',
                "X-Lunar-Export-Id": str(export_id),
                "X-Lunar-Snapshot-At": receipt["snapshot_at"],
                "X-Lunar-Workflow-Id": receipt["workflow_id"],
            },
        )
    except (VersionNotFound, WorkflowNotFound):
        workspace.__exit__(None, None, None)
        return JSONResponse({"error": "Workflow not found"}, status_code=404)
    except (ExportError, PackageValidationError, ValueError, OSError):
        workspace.__exit__(None, None, None)
        return JSONResponse(
            {
                "error": "Workflow export failed integrity validation; no archive published"
            },
            status_code=409,
        )
    except BaseException:
        workspace.__exit__(None, None, None)
        raise
    finally:
        if connection is not None:
            await connection.close()


def register_export_routes(mcp):
    mcp.custom_route("/api/packages/versions/{version_id}/export", methods=["GET"])(
        export_package
    )
    mcp.custom_route(
        "/api/packages/versions/{version_id}/workflows/{workflow_id}/export",
        methods=["GET"],
    )(export_workflow_package)
