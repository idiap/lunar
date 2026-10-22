# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Authenticated multipart import and owner-filtered package/version navigation."""

import asyncio
import logging
import os
from pathlib import Path
from uuid import UUID

from starlette.responses import JSONResponse

from modules import common
from modules.common import authenticated_user, connect, record_json
from .archive import ArchiveLimits, validate_archive
from .format.contract import PackageValidationError
from .importer import import_validated, reconcile_imports, remove_version_files
from .repository import list_versions
from .storage import VersionStorage
from .upload import receive_zip
from .workspace import upload_workspace, recover_uploads
from .worker.preparation import (
    prepare_runtime,
    recover_runtime_preparations,
    remove_runtime_image,
    runtime_lock_key,
)
from .worker.sandbox import WorkerUnavailable
from .context import owned_context, PackageContext, VersionNotFound

LOGGER = logging.getLogger(__name__)
DELETE_TASKS = set()


def configured_storage():
    return VersionStorage(
        Path(os.getenv("LUNAR_PACKAGE_STORAGE_ROOT", "./var/packages")).resolve()
    )


async def recover_package_imports():
    connection = await connect()
    try:
        storage = configured_storage()
        await reconcile_imports(connection, storage)
        await recover_runtime_preparations(connection)
        await asyncio.to_thread(
            recover_uploads, storage, database_url=common.DATABASE_URL
        )
        deleting = await connection.fetch("""SELECT id,user_id,package_id,version
            FROM package_versions WHERE deletion_started_at IS NOT NULL""")
    finally:
        await connection.close()
    for row in deleting:
        start_package_deletion(PackageContext.from_record(row))


async def import_package(request):
    owner = await authenticated_user(request)
    if isinstance(owner, JSONResponse):
        return owner
    if request.query_params:
        return JSONResponse(
            {"error": "Import accepts no owner or context overrides"}, status_code=400
        )
    storage, limits = configured_storage(), ArchiveLimits.from_environment()
    try:
        with upload_workspace(storage, database_url=common.DATABASE_URL) as temporary:
            path = await receive_zip(request, temporary / "upload.zip", limits)
            archive = await asyncio.to_thread(
                validate_archive, path, temporary / "validated", limits
            )
            connection = await connect()
            try:
                context = await import_validated(
                    connection, storage, user_id=owner["id"], archive=archive
                )
                row = await connection.fetchrow(
                    """SELECT id,package_id,version,status,runtime_state,error,created_at
                    FROM package_versions WHERE id=$1 AND user_id=$2""",
                    context.version_id,
                    owner["id"],
                )
            finally:
                await connection.close()
        if row is None:
            raise RuntimeError("Imported package version was not persisted")
        return JSONResponse({"version": record_json(row)}, status_code=201)
    except PackageValidationError as exc:
        return JSONResponse(
            {"error": str(exc), "code": "invalid_package"}, status_code=400
        )
    except Exception:
        return JSONResponse(
            {
                "error": "Package import failed; previous versions remain available",
                "code": "import_failed",
            },
            status_code=500,
        )


async def package_versions(request):
    owner = await authenticated_user(request)
    if isinstance(owner, JSONResponse):
        return owner
    if request.query_params:
        return JSONResponse(
            {"error": "Version listing accepts no owner override"}, status_code=400
        )
    connection = await connect()
    try:
        rows = await list_versions(connection, owner["id"])
        return JSONResponse({"versions": [record_json(row) for row in rows]})
    finally:
        await connection.close()


async def delete_package_version(request):
    owner = await authenticated_user(request)
    if isinstance(owner, JSONResponse):
        return owner
    if request.query_params or await request.body():
        return JSONResponse(
            {"error": "Package deletion accepts no overrides"}, status_code=400
        )
    try:
        identity = UUID(request.path_params["version_id"])
    except ValueError:
        return JSONResponse({"error": "Package version not found"}, status_code=404)
    connection = await connect()
    lock_key = runtime_lock_key(identity)
    locked = False
    try:
        locked = await connection.fetchval("SELECT pg_try_advisory_lock($1)", lock_key)
        if not locked:
            return JSONResponse(
                {"error": "This package runtime is currently being prepared"},
                status_code=409,
            )
        async with connection.transaction():
            row = await connection.fetchrow(
                """SELECT id,package_id,user_id,version,deletion_started_at
                FROM package_versions WHERE id=$1 AND user_id=$2 AND status='ready' FOR UPDATE""",
                identity,
                owner["id"],
            )
            if row is None:
                return JSONResponse(
                    {"error": "Package version not found"}, status_code=404
                )
            if row["deletion_started_at"] is not None:
                return JSONResponse(
                    {"error": "Package deletion is already in progress"},
                    status_code=409,
                )
            active = await connection.fetchval(
                """SELECT EXISTS(SELECT 1 FROM prism_runs
                WHERE version_id=$1 AND user_id=$2 AND state IN ('queued','running'))""",
                identity,
                owner["id"],
            )
            if active:
                return JSONResponse(
                    {
                        "error": "A package with queued or running workflows cannot be deleted"
                    },
                    status_code=409,
                )
            context = PackageContext.from_record(row)
            await connection.execute(
                """UPDATE package_versions SET deletion_started_at=NOW(),error=NULL
                WHERE id=$1 AND user_id=$2""",
                identity,
                owner["id"],
            )
    finally:
        if locked and not connection.is_closed():
            await connection.execute("SELECT pg_advisory_unlock($1)", lock_key)
        await connection.close()
    start_package_deletion(context)
    return JSONResponse({"success": True, "state": "deleting"}, status_code=202)


def start_package_deletion(context):
    task = asyncio.create_task(finish_package_deletion(context))
    DELETE_TASKS.add(task)
    task.add_done_callback(DELETE_TASKS.discard)


async def finish_package_deletion(context):
    identity = context.version_id
    connection = await connect()
    lock_key = runtime_lock_key(identity)
    locked = False
    try:
        await connection.execute("SELECT pg_advisory_lock($1)", lock_key)
        locked = True
        async with connection.transaction():
            row = await connection.fetchrow(
                """SELECT runtime_state,runtime_image FROM package_versions
                WHERE id=$1 AND user_id=$2 AND deletion_started_at IS NOT NULL FOR UPDATE""",
                identity,
                context.user_id,
            )
            if row is None:
                return
            # Delete restrictive dependants before the package-version cascade.
            await connection.execute(
                "DELETE FROM chats WHERE version_id=$1 AND user_id=$2",
                identity,
                context.user_id,
            )
            await connection.execute(
                "DELETE FROM reports WHERE version_id=$1 AND user_id=$2",
                identity,
                context.user_id,
            )
            await connection.execute(
                "DELETE FROM prism_runs WHERE version_id=$1 AND user_id=$2",
                identity,
                context.user_id,
            )
            await connection.execute(
                "DELETE FROM package_versions WHERE id=$1 AND user_id=$2",
                identity,
                context.user_id,
            )
    except Exception:
        LOGGER.exception("Package version %s deletion failed", identity)
        try:
            await connection.execute(
                """UPDATE package_versions SET deletion_started_at=NULL,
                error='Package deletion failed; please retry' WHERE id=$1 AND user_id=$2""",
                identity,
                context.user_id,
            )
        except Exception:
            LOGGER.exception(
                "Package version %s deletion failure could not be recorded", identity
            )
        return
    finally:
        if locked and not connection.is_closed():
            await connection.execute("SELECT pg_advisory_unlock($1)", lock_key)
        await connection.close()

    async def cleanup_artifact(name, cleanup, *arguments):
        try:
            await asyncio.to_thread(cleanup, *arguments)
        except Exception:
            LOGGER.exception(
                "Package version %s %s cleanup was incomplete", identity, name
            )

    cleanup_tasks = [
        cleanup_artifact("files", remove_version_files, configured_storage(), context)
    ]
    if row["runtime_state"] != "unprepared" or row["runtime_image"]:
        cleanup_tasks.append(
            cleanup_artifact("runtime image", remove_runtime_image, identity)
        )
    await asyncio.gather(*cleanup_tasks)


async def import_result(request):
    owner = await authenticated_user(request)
    if isinstance(owner, JSONResponse):
        return owner
    try:
        identity = UUID(request.path_params["version_id"])
    except ValueError:
        return JSONResponse({"error": "Import not found"}, status_code=404)
    connection = await connect()
    try:
        row = await connection.fetchrow(
            """SELECT id,package_id,version,status,runtime_state,error,created_at
            FROM package_versions WHERE id=$1 AND user_id=$2""",
            identity,
            owner["id"],
        )
        if row is None:
            return JSONResponse({"error": "Import not found"}, status_code=404)
        return JSONResponse({"version": record_json(row)})
    finally:
        await connection.close()


async def prepare_package(request):
    owner = await authenticated_user(request)
    if isinstance(owner, JSONResponse):
        return owner
    if request.query_params or await request.body():
        return JSONResponse(
            {"error": "Runtime preparation accepts no overrides"}, status_code=400
        )
    connection = await connect()
    try:
        try:
            context = await owned_context(
                connection, owner["id"], UUID(request.path_params["version_id"])
            )
        except (ValueError, VersionNotFound):
            return JSONResponse({"error": "Package version not found"}, status_code=404)
        base_image = os.getenv("LUNAR_WORKER_IMAGE")
        if not base_image:
            return JSONResponse(
                {"error": "Worker base image is not configured"}, status_code=503
            )
        try:
            await prepare_runtime(
                connection, context, configured_storage(), base_image=base_image
            )
        except WorkerUnavailable as exc:
            return JSONResponse({"error": str(exc)}, status_code=409)
        except Exception:
            return JSONResponse(
                {"error": "Runtime preparation failed; inspect its status"},
                status_code=503,
            )
        return JSONResponse({"runtime_state": "ready"})
    finally:
        await connection.close()


def register_package_routes(mcp):
    mcp.custom_route("/api/packages/versions/{version_id}/prepare", methods=["POST"])(
        prepare_package
    )
    mcp.custom_route("/api/packages/versions/{version_id}", methods=["DELETE"])(
        delete_package_version
    )
    mcp.custom_route("/api/packages/import", methods=["POST"])(import_package)
    mcp.custom_route("/api/packages/versions", methods=["GET"])(package_versions)
    mcp.custom_route("/api/packages/imports/{version_id}", methods=["GET"])(
        import_result
    )
