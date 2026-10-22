# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Authenticated selected-package execution through host-controlled workers."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import os
import shutil
import threading

from domain_packages.context import (
    CURRENT_VERSION,
    SelectionRequired,
    VersionNotFound,
    owned_context,
)
from domain_packages.routes import configured_storage
from domain_packages.worker.runtime import load_runtime
from domain_packages.worker.runs import (
    enqueue,
    execute_queued,
    recover_runs as recover_worker_runs,
)
from domain_packages.worker.sandbox import WorkerUnavailable
from modules.ai_models import load_owned_ai_model
from modules.common import connect, json_value

WORKERS = ThreadPoolExecutor(
    max_workers=max(1, int(os.getenv("LUNAR_PRISM_WORKERS", "2"))),
    thread_name_prefix="lunar-worker",
)
ACTIVE_TASKS = set()
ACTIVE_RUNS = {}
RunUnavailableError = WorkerUnavailable


class AIModelNotFoundError(LookupError):
    pass


def selected_context(user_id=None):
    context = CURRENT_VERSION.get()
    if context is None:
        raise SelectionRequired("Select an imported package version")
    if user_id is not None and context.user_id != user_id:
        raise VersionNotFound("Package version not found")
    return context


async def accept_run(*, user_id, workflow_id, request):
    context = selected_context(user_id)
    connection = await connect()
    try:
        runtime = await load_runtime(
            connection, user_id, context.version_id, configured_storage()
        )
        if runtime.context != context:
            raise VersionNotFound("Package context does not match the owned version")
        selected_model = None
        if request.ai_model_id is not None:
            selected_model = await load_owned_ai_model(
                connection, model_id=request.ai_model_id, user_id=user_id
            )
            if selected_model is None:
                raise AIModelNotFoundError("AI model not found")
        if request.network_authority and os.getenv("LUNAR_ALLOW_LIVE_NETWORK") != "1":
            raise PermissionError(
                "Public network access is disabled by this deployment"
            )
        run_id, accepted = await enqueue(
            connection,
            runtime,
            workflow_id,
            inputs=request.inputs,
            selected_model=selected_model,
            network_authority=request.network_authority,
        )
    except BaseException:
        await connection.close()
        raise
    cancelled = threading.Event()
    task = asyncio.create_task(
        _execute_run(connection, runtime, run_id, selected_model, cancelled)
    )
    ACTIVE_TASKS.add(task)
    task.add_done_callback(ACTIVE_TASKS.discard)
    ACTIVE_RUNS[run_id] = cancelled
    task.add_done_callback(lambda _: ACTIVE_RUNS.pop(run_id, None))
    return run_id, accepted


async def _execute_run(connection, runtime, run_id, selected_model, cancelled):
    try:
        return await execute_queued(
            connection,
            runtime,
            run_id,
            selected_model=selected_model,
            cancelled=cancelled,
            executor=WORKERS,
        )
    finally:
        await connection.close()


def stop_run(run_id):
    """Signal the locally executing worker; its normal finalizer persists the result."""
    cancelled = ACTIVE_RUNS.get(run_id)
    if cancelled is None:
        return False
    cancelled.set()
    return True


async def recover_runs():
    connection = await connect()
    try:
        return len(await recover_worker_runs(connection))
    finally:
        await connection.close()


async def public_workflows():
    context = selected_context()
    connection = await connect()
    try:
        if (
            await owned_context(connection, context.user_id, context.version_id)
            != context
        ):
            raise VersionNotFound("Package context does not match the owned version")
        value = await connection.fetchval(
            "SELECT manifest FROM package_versions WHERE id=$1 AND user_id=$2",
            context.version_id,
            context.user_id,
        )
        manifest = json.loads(value) if isinstance(value, str) else value
        if not isinstance(manifest, dict):
            raise VersionNotFound("Package manifest not found")
        from domain_packages.source_workflows import runtime_manifest
        from domain_packages.routes import configured_storage

        manifest = runtime_manifest(
            manifest, configured_storage().version_root(context)
        )
        sources = [
            json_value(row["document"], {})
            for row in await connection.fetch(
                "SELECT document FROM package_resources WHERE user_id=$1 AND version_id=$2 AND collection='data-sources'",
                context.user_id,
                context.version_id,
            )
        ]

        def datasets(workflow_id):
            return [
                {
                    **dataset,
                    "resource_id": source["id"],
                    "visibility": source["descriptor"].get("visibility", "package"),
                    "status": (
                        "available"
                        if dataset.get("files")
                        else dataset.get("status", "unavailable")
                    ),
                }
                for source in sources
                for dataset in source["descriptor"].get("datasets", [])
                if workflow_id in dataset.get("workflow_ids", [])
            ]

        return [
            {
                **row,
                "sources": [
                    source["id"]
                    for source in sources
                    if any(
                        row["id"] in item.get("workflow_ids", [])
                        for item in source["descriptor"].get("datasets", [])
                    )
                ],
                "datasets": datasets(row["id"]),
                "operations": ["run"],
                "output_key": row.get("metadata", {}).get("output_key", "result"),
                "downloads_enabled": os.getenv("LUNAR_ALLOW_LIVE_NETWORK") == "1",
            }
            for row in manifest["runtime"]["workflows"]
        ]
    finally:
        await connection.close()


def delete_run_artifacts(*, run_id, workflow_id):
    root = configured_storage().run_root(selected_context(), run_id)
    if root.exists():
        shutil.rmtree(root)
