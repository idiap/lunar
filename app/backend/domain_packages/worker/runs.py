# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Owned durable run transitions around the isolated worker contract."""

import asyncio
import hashlib
import json
from functools import partial
import threading
from uuid import uuid4, uuid5

from jsonschema import Draft202012Validator

from ..context import VersionNotFound, owned_context
from .sandbox import WorkerLimits as WorkerLimits, WorkerUnavailable


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return "sha256:" + hashlib.sha256(encoded(value).encode()).hexdigest()


def lock_key(run_id):
    return int.from_bytes(
        hashlib.sha256(("worker-run:" + str(run_id)).encode()).digest()[:8], signed=True
    )


def reasoning_contract(workflow):
    """Return the host-derived reasoning contract for a registered workflow."""
    metadata = workflow.get("metadata", {})
    viewer_id = metadata.get("viewer_workflow_id")
    if not isinstance(viewer_id, str) or not viewer_id:
        return None
    contract = metadata.get("reasoning_contract")
    if contract is None:
        # Stored pre-contract registrations still fail closed on the exact
        # reasoning workflow encoded in their validated viewer identity.
        _, separator, name = viewer_id.rpartition(":")
        if not separator or not name:
            raise WorkerUnavailable("invalid PRISM reasoning contract")
        return {"workflow": name, "steps": None}
    if (
        not isinstance(contract, dict)
        or not isinstance(contract.get("workflow"), str)
        or not contract["workflow"]
        or not isinstance(contract.get("steps"), list)
        or any(not isinstance(step, str) or not step for step in contract["steps"])
        or len(contract["steps"]) != len(set(contract["steps"]))
    ):
        raise WorkerUnavailable("invalid PRISM reasoning contract")
    return contract


async def require_complete_reasoning_log(connection, context, run_id, workflow):
    """Fail closed unless every declared Prism occurrence was durably recorded."""
    contract = reasoning_contract(workflow)
    if contract is None or contract["steps"] == []:
        return
    rows = await connection.fetch(
        """SELECT source_event_key,event_kind,source
        FROM prism_reasoning_entries
        WHERE run_id=$1 AND user_id=$2 AND version_id=$3
        ORDER BY sequence""",
        run_id,
        context.user_id,
        context.version_id,
    )
    transitions = {}
    for row in rows:
        source = row["source"]
        if isinstance(source, str):
            source = json.loads(source)
        if row["event_kind"] != "stage" or not isinstance(source, dict):
            continue
        step = source.get("reasoning_step")
        if not isinstance(step, dict) or step.get("workflow") != contract["workflow"]:
            continue
        name = step.get("name")
        status = source.get("status")
        event_key = row["source_event_key"]
        occurrence, separator, key_status = event_key.rpartition(":")
        if (
            not isinstance(name, str)
            or not name
            or not separator
            or key_status != status
        ):
            raise WorkerUnavailable("PRISM reasoning log contains an invalid step")
        recorded = transitions.setdefault(occurrence, {"name": name, "statuses": []})
        if recorded["name"] != name:
            raise WorkerUnavailable("PRISM reasoning log contains an invalid step")
        recorded["statuses"].append(status)
    if not transitions:
        raise WorkerUnavailable(
            "PRISM reasoning log is required but no reasoning steps were recorded"
        )
    if any(
        recorded["statuses"] != ["running", "completed"]
        for recorded in transitions.values()
    ):
        raise WorkerUnavailable("PRISM reasoning log has incomplete step transitions")
    expected = contract["steps"]
    if expected is not None and sorted(expected) != sorted(
        recorded["name"] for recorded in transitions.values()
    ):
        raise WorkerUnavailable("PRISM reasoning log is missing required steps")


async def enqueue(
    connection,
    runtime,
    workflow_id,
    *,
    inputs,
    selected_model=None,
    network_authority=False,
):
    context = runtime.context
    if await owned_context(connection, context.user_id, context.version_id) != context:
        raise VersionNotFound("Package context does not match the owned version")
    workflow = runtime.workflow(workflow_id)
    Draft202012Validator(workflow["input_schema"]).validate(inputs)
    run_id = uuid4()
    model_snapshot = selected_model.safe_snapshot if selected_model else None
    accepted = {
        "version_id": str(context.version_id),
        "workflow_id": workflow_id,
        "inputs": inputs,
        "network_authority": network_authority,
        "model": model_snapshot,
        "runtime_image": runtime.image,
    }
    accepted_digest = digest(accepted)
    # The accepting connection owns this lease until it closes after execution.
    await connection.execute("SELECT pg_advisory_lock($1)", lock_key(run_id))
    async with connection.transaction():
        await connection.execute(
            """INSERT INTO prism_runs
            (id,user_id,version_id,workflow_id,operation,mode,state,safe_input_manifest,
             accepted_plan_digest,artifact_root,ai_model_id,ai_model_snapshot)
            VALUES($1,$2,$3,$4,'run',$5,'queued',$6::jsonb,$7,$8,$9,$10::jsonb)""",
            run_id,
            context.user_id,
            context.version_id,
            workflow_id,
            "run",
            encoded(accepted),
            accepted_digest,
            str(runtime.storage.run_root(context, run_id)),
            selected_model.id if selected_model else None,
            encoded(model_snapshot),
        )
        for source in workflow.get("metadata", {}).get("source_bindings", []):
            await connection.execute(
                """INSERT INTO prism_run_planned_sources
                (id,run_id,user_id,version_id,resource_id,source_local_identifier,required,binding_metadata)
                VALUES($1,$2,$3,$4,$5,$6,$7,$8::jsonb)""",
                uuid4(),
                run_id,
                context.user_id,
                context.version_id,
                source["resource_id"],
                source.get("local_identifier"),
                source.get("required", True),
                encoded(source.get("metadata", {})),
            )
    return run_id, accepted_digest


async def append_event(connection, context, run_id, event):
    """Commit each observed frame before allowing the worker to continue."""
    async with connection.transaction():
        row = await connection.fetchrow(
            "SELECT workflow_id,state FROM prism_runs WHERE id=$1 AND user_id=$2 AND version_id=$3 FOR UPDATE",
            run_id,
            context.user_id,
            context.version_id,
        )
        if row is None or row["state"] != "running":
            raise WorkerUnavailable("run is not active in the selected version")
        identity = uuid5(run_id, "worker-event:" + str(event["sequence"]))
        await connection.execute(
            """INSERT INTO prism_run_events
            (id,run_id,user_id,version_id,stage_id,component_id,status,started_at,safe_summary,detail)
            VALUES($1,$2,$3,$4,$5,$6,'observed',NOW(),$7,$8::jsonb)""",
            identity,
            run_id,
            context.user_id,
            context.version_id,
            "worker:" + str(event["sequence"]),
            row["workflow_id"],
            event["kind"],
            encoded({"worker_event": event}),
        )
    # Keep the raw frame even if its optional typed projection is invalid.
    from .observations import project_event

    async with connection.transaction():
        reasoning_entry = await project_event(connection, context, run_id, event)
    if reasoning_entry:
        from domain_packages.context import bind_context
        from prism_runs.reasoning_enrichment import schedule_enrichment

        with bind_context(context):
            schedule_enrichment(reasoning_entry)


async def execute_queued(
    connection,
    runtime,
    run_id,
    *,
    selected_model=None,
    cancelled=None,
    completion=None,
    limits=None,
    executor=None,
):
    """Persist failure or an atomically released output; never resume imported runs."""
    context = runtime.context
    if not await connection.fetchval(
        "SELECT pg_try_advisory_lock($1)", lock_key(run_id)
    ):
        raise WorkerUnavailable("run is already executing")
    cancelled = cancelled or threading.Event()
    loop = asyncio.get_running_loop()
    try:
        row = await connection.fetchrow(
            """UPDATE prism_runs SET state='running',started_at=NOW()
            WHERE id=$1 AND user_id=$2 AND version_id=$3 AND state='queued' AND imported=FALSE
            RETURNING workflow_id,safe_input_manifest,ai_model_id""",
            run_id,
            context.user_id,
            context.version_id,
        )
        if row is None:
            raise WorkerUnavailable(
                "queued run is not available in the selected version"
            )
        packet = (
            json.loads(row["safe_input_manifest"])
            if isinstance(row["safe_input_manifest"], str)
            else row["safe_input_manifest"]
        )

        def observed(event):
            asyncio.run_coroutine_threadsafe(
                append_event(connection, context, run_id, event), loop
            ).result()

        interrupted = False
        failed_result = None
        try:
            if cancelled.is_set():
                raise WorkerUnavailable("Stopped by user")
            if packet["runtime_image"] != runtime.image or row["ai_model_id"] != (
                selected_model.id if selected_model else None
            ):
                raise WorkerUnavailable("accepted runtime or selected model changed")
            task = loop.run_in_executor(
                executor,
                partial(
                    runtime.execute,
                    row["workflow_id"],
                    inputs=packet["inputs"],
                    run_id=run_id,
                    selected_model=selected_model,
                    network_authority=packet["network_authority"],
                    on_event=observed,
                    cancelled=cancelled,
                    completion=completion,
                    limits=limits,
                ),
            )
            try:
                result = await asyncio.shield(task)
            except asyncio.CancelledError:
                interrupted = True
                cancelled.set()
                try:
                    await asyncio.shield(task)
                except Exception:
                    pass
                raise WorkerUnavailable("worker interrupted")
            if cancelled.is_set():
                raise WorkerUnavailable("Stopped by user")
            if result["status"] != "succeeded":
                failed_result = result
                raise WorkerUnavailable(
                    (result["error"] or {}).get("message") or "package execution failed"
                )
            workflow = runtime.workflow(row["workflow_id"])
            await require_complete_reasoning_log(connection, context, run_id, workflow)
            metadata = workflow.get("metadata", {})
            output_id = uuid4()
            output_key = metadata.get("output_key", "result")
            terminal_digest = digest(result)
            from provenance.service import persist_run_provenance

            async with connection.transaction():
                if cancelled.is_set():
                    raise WorkerUnavailable("Stopped by user")
                for artifact in result["artifacts"]:
                    await connection.execute(
                        """INSERT INTO prism_run_artifacts
                        (id,run_id,user_id,version_id,artifact_key,safe_locator,media_type,content_digest,provenance_entity_id)
                        VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9)""",
                        uuid4(),
                        run_id,
                        context.user_id,
                        context.version_id,
                        artifact["path"],
                        artifact["path"],
                        artifact["media_type"],
                        "sha256:" + artifact["sha256"],
                        f'entity:run:{run_id}:artifact:{artifact["path"]}',
                    )
                await connection.execute(
                    """INSERT INTO prism_run_outputs
                    (id,run_id,user_id,version_id,output_key,component_id,markdown,structured_value,media_type,content_digest,provenance_entity_id)
                    VALUES($1,$2,$3,$4,$5,$6,$7,$8::jsonb,'text/markdown',$9,$10)""",
                    output_id,
                    run_id,
                    context.user_id,
                    context.version_id,
                    output_key,
                    metadata.get("output_component_id", workflow["id"]),
                    result["result"]["markdown"],
                    encoded(result["result"]["structured_value"]),
                    "sha256:"
                    + hashlib.sha256(result["result"]["markdown"].encode()).hexdigest(),
                    f"entity:run:{run_id}:output:{output_key}",
                )
                await connection.execute(
                    """INSERT INTO prism_run_events
                    (id,run_id,user_id,version_id,stage_id,component_id,status,started_at,finished_at,safe_summary,detail)
                    VALUES($1,$2,$3,$4,'worker:result',$5,'completed',NOW(),NOW(),'Validated worker result',$6::jsonb)""",
                    uuid5(run_id, "worker-result"),
                    run_id,
                    context.user_id,
                    context.version_id,
                    workflow["id"],
                    encoded({"worker_result": result}),
                )
                if cancelled.is_set():
                    raise WorkerUnavailable("Stopped by user")
                changed = await connection.execute(
                    "UPDATE prism_runs SET state='completed',finished_at=NOW(),terminal_result_digest=$4 WHERE id=$1 AND user_id=$2 AND version_id=$3 AND state='running'",
                    run_id,
                    context.user_id,
                    context.version_id,
                    terminal_digest,
                )
                if changed != "UPDATE 1":
                    raise WorkerUnavailable("run cannot transition to completed")
                await persist_run_provenance(
                    connection, context, run_id, workflow, failed=False
                )
                if cancelled.is_set():
                    raise WorkerUnavailable("Stopped by user")
            return {
                "state": "completed",
                "output_id": output_id,
                "terminal_digest": terminal_digest,
            }
        except Exception as exc:
            stopped = cancelled.is_set() and not interrupted
            state = "cancelled" if stopped else "failed"
            message = "Stopped by user" if stopped else str(exc)[:1000]
            terminal_digest = digest(
                {"run_id": str(run_id), "state": state, "error": message}
            )
            async with connection.transaction():
                if failed_result is not None and not stopped:
                    for artifact in failed_result["artifacts"]:
                        await connection.execute(
                            """INSERT INTO prism_run_artifacts
                            (id,run_id,user_id,version_id,artifact_key,safe_locator,media_type,content_digest,provenance_entity_id)
                            VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9)""",
                            uuid4(),
                            run_id,
                            context.user_id,
                            context.version_id,
                            artifact["path"],
                            artifact["path"],
                            artifact["media_type"],
                            "sha256:" + artifact["sha256"],
                            f'entity:run:{run_id}:artifact:{artifact["path"]}',
                        )
                    await connection.execute(
                        """INSERT INTO prism_run_events
                        (id,run_id,user_id,version_id,stage_id,component_id,status,started_at,finished_at,safe_summary,detail)
                        VALUES($1,$2,$3,$4,'worker:result',$5,'failed',NOW(),NOW(),'Failed worker result',$6::jsonb)""",
                        uuid5(run_id, "worker-result"),
                        run_id,
                        context.user_id,
                        context.version_id,
                        row["workflow_id"],
                        encoded({"worker_result": failed_result}),
                    )
                await connection.execute(
                    "UPDATE prism_runs SET state=$4,finished_at=NOW(),error_summary=$5,terminal_result_digest=$6 WHERE id=$1 AND user_id=$2 AND version_id=$3 AND state='running'",
                    run_id,
                    context.user_id,
                    context.version_id,
                    state,
                    message,
                    terminal_digest,
                )
                from provenance.service import persist_run_provenance

                await persist_run_provenance(
                    connection,
                    context,
                    run_id,
                    runtime.workflow(row["workflow_id"]),
                    failed=True,
                )
            if interrupted:
                raise asyncio.CancelledError
            return {
                "state": state,
                "error": message,
                "terminal_digest": terminal_digest,
            }
    finally:
        await connection.execute("SELECT pg_advisory_unlock($1)", lock_key(run_id))


async def recover_runs(connection):
    """Fail abandoned accepted work while respecting other live worker processes."""
    recovered = []
    for row in await connection.fetch(
        "SELECT id,user_id,version_id,workflow_id FROM prism_runs WHERE state IN ('queued','running') AND imported=FALSE"
    ):
        if not await connection.fetchval(
            "SELECT pg_try_advisory_lock($1)", lock_key(row["id"])
        ):
            continue
        try:
            context = await owned_context(connection, row["user_id"], row["version_id"])
            terminal = digest(
                {
                    "run_id": str(row["id"]),
                    "state": "failed",
                    "error": "worker_interrupted",
                }
            )
            async with connection.transaction():
                changed = await connection.execute(
                    "UPDATE prism_runs SET state='failed',finished_at=NOW(),error_summary='worker_interrupted',terminal_result_digest=$2 WHERE id=$1 AND state IN ('queued','running') AND imported=FALSE",
                    row["id"],
                    terminal,
                )
                if changed == "UPDATE 1":
                    from provenance.service import persist_run_provenance

                    await persist_run_provenance(
                        connection,
                        context,
                        row["id"],
                        {"id": row["workflow_id"]},
                        failed=True,
                    )
                    recovered.append(row["id"])
        finally:
            await connection.execute(
                "SELECT pg_advisory_unlock($1)", lock_key(row["id"])
            )
    return recovered
