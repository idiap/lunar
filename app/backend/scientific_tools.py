# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Opaque, version-bound planning and quality gates around declared package workers."""

import hashlib
import json
from uuid import UUID
from typing import Any

from control_plane import tools as control_tools
from domain_packages.context import require_context
from lunar_planner.ports import current_ports
from state import STATE


def _digest(value):
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(
                value,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode()
        ).hexdigest()
    )


def _inspect_capability(
    *,
    component_ids=None,
    kinds=None,
    include=None,
    planner_receipt_digest=None,
    **kwargs,
):
    surface = current_ports().surface
    if surface is None:
        raise RuntimeError("planner surface is not configured")
    catalog = surface.snapshot()
    by_id = {
        row["id"]: row for row in [*catalog["skills"], *catalog["workflow_packages"]]
    }
    if not component_ids or any(identity not in by_id for identity in component_ids):
        raise ValueError("Capability not found in the selected version")
    return {
        "mode": "exact",
        "components": [by_id[identity] for identity in component_ids],
        "execution_performed": False,
    }


def _target_is_bound_to_handoff(receipt, target_id, target_kind):
    selected = (
        receipt.get("execution_handoff") or receipt.get("delivery_handoff") or {}
    ).get("selected_target", {})
    return selected.get("id") == target_id


async def _prepare_execution_reference(
    planner_result_id,
    *,
    target_id=None,
    target_kind="auto",
    operation=None,
    principal="anonymous",
    supplied_inputs=None,
    ai_model_id=None,
):
    from domain_packages.worker.runtime import load_runtime
    from domain_packages.routes import configured_storage
    from modules.common import connect
    from modules.ai_models import load_owned_ai_model
    from jsonschema import Draft202012Validator

    context = require_context(UUID(principal) if principal != "anonymous" else None)
    planned = STATE.get(planner_result_id, "planner_result")
    receipt = _finalized_planner_receipt(planned)
    target = planned.get("execution_target") or {}
    selected = target_id or target.get("id")
    if selected != target.get("id") or not _target_is_bound_to_handoff(
        receipt, selected, target_kind
    ):
        raise ValueError("Execution target differs from the locked planner route")
    if target_kind != "auto" and target_kind != target.get("kind"):
        raise ValueError("Execution target kind differs from the locked planner route")
    if operation and target.get("operation") and operation != target["operation"]:
        raise ValueError("Operation differs from the locked planner route")
    blockers = []
    surface = current_ports().surface
    if surface is None:
        raise RuntimeError("planner surface is not configured")
    catalog = surface.snapshot()
    workflow = next(
        (row for row in catalog["workflow_packages"] if row["id"] == selected), None
    )
    if workflow is None:
        blockers.append("The selected capability has no registered worker workflow.")
        registration = None
    else:
        registration = workflow["registration"]
    inputs = dict(supplied_inputs or {})
    image = None
    if registration:
        blockers.extend(
            error.message
            for error in Draft202012Validator(registration["input_schema"]).iter_errors(
                inputs
            )
        )
        connection = await connect()
        try:
            runtime = await load_runtime(
                connection, context.user_id, context.version_id, configured_storage()
            )
            image = runtime.image
            if (
                ai_model_id
                and await load_owned_ai_model(
                    connection, model_id=UUID(str(ai_model_id)), user_id=context.user_id
                )
                is None
            ):
                blockers.append("AI model not found.")
        finally:
            await connection.close()
    prepared = {
        "target_id": selected,
        "target_kind": target.get("kind"),
        "workflow_id": registration["id"] if registration else None,
        "inputs": inputs,
        "ai_model_id": str(ai_model_id) if ai_model_id else None,
        "runtime_image": image,
        "planner_receipt_digest": receipt.get("digest"),
        "version_id": str(context.version_id),
        "status": "blocked" if blockers else "ready_for_acceptance",
        "preflight": {"blockers": blockers},
    }
    prepared["accepted_plan_digest"] = _digest(prepared)
    identity = STATE.put(
        "prepared_execution",
        {
            "prepared_execution": prepared,
            "planner_result_id": planner_result_id,
            "principal": principal,
        },
    )
    return {
        **prepared,
        "prepared_execution_id": identity,
        "execution_performed": False,
        "state_scope": "server_process",
    }


async def execute_prepared_reference(prepared_execution_id, *, channel):
    from domain_packages.worker.runtime import load_runtime
    from domain_packages.worker.runs import enqueue, execute_queued
    from domain_packages.routes import configured_storage
    from modules.common import connect, json_value
    from modules.ai_models import load_owned_ai_model

    record = STATE.take(prepared_execution_id, "prepared_execution")
    prepared = record["prepared_execution"]
    context = require_context(
        UUID(record["principal"]) if record["principal"] != "anonymous" else None
    )
    if prepared["status"] != "ready_for_acceptance":
        raise ValueError("Blocked execution cannot run")
    unsigned = {
        key: value for key, value in prepared.items() if key != "accepted_plan_digest"
    }
    if _digest(unsigned) != prepared["accepted_plan_digest"]:
        raise ValueError("Prepared execution digest mismatch")
    connection = await connect()
    try:
        runtime = await load_runtime(
            connection, context.user_id, context.version_id, configured_storage()
        )
        if runtime.image != prepared["runtime_image"]:
            raise ValueError("Prepared runtime changed")
        model = (
            await load_owned_ai_model(
                connection,
                model_id=UUID(prepared["ai_model_id"]),
                user_id=context.user_id,
            )
            if prepared["ai_model_id"]
            else None
        )
        if prepared["ai_model_id"] and model is None:
            raise ValueError("AI model not found")
        run_id, accepted = await enqueue(
            connection,
            runtime,
            prepared["workflow_id"],
            inputs=prepared["inputs"],
            selected_model=model,
        )
        outcome = await execute_queued(
            connection, runtime, run_id, selected_model=model
        )
        terminal = await connection.fetchval(
            "SELECT detail FROM prism_run_events WHERE run_id=$1 AND user_id=$2 AND version_id=$3 AND stage_id='worker:result'",
            run_id,
            context.user_id,
            context.version_id,
        )
        result = json_value(terminal, {})
        candidate = dict(result.get("worker_result", {}).get("result") or {})
        candidate["status"] = "success" if outcome["state"] == "completed" else "failed"
        candidate["execution_performed"] = outcome["state"] == "completed"
        candidate["execution_receipt"] = {
            "plan_digest": prepared["accepted_plan_digest"],
            "worker_request_digest": accepted,
            "fallback_used": False,
            "mutation": False,
            "run_id": str(run_id),
            "version_id": str(context.version_id),
        }
        run = {
            "schema_version": "mcp.run/v1",
            "run_id": str(run_id),
            "target_id": prepared["target_id"],
            "target_kind": prepared["target_kind"],
            "accepted_plan_digest": prepared["accepted_plan_digest"],
            "status": "success" if outcome["state"] == "completed" else "failed",
            "result": candidate,
            "network": False,
            "mutation": False,
            "acceptance_receipt": {
                "schema_version": "mcp.execution-acceptance/v1",
                "mechanism": "automatic",
                "channel": channel,
                "principal": record["principal"],
                "action": "accept",
                "accepted_plan_digest": prepared["accepted_plan_digest"],
            },
        }
        run["digest"] = _digest(run)
        identity = STATE.put(
            "run", {"run": run, "planner_result_id": record["planner_result_id"]}
        )
        return {
            **run,
            "run_id": identity,
            "execution_run_id": str(run_id),
            "state_scope": "server_process",
        }
    finally:
        await connection.close()


def _inspect_run(run):
    unsigned = {key: value for key, value in run.items() if key != "digest"}
    if run.get("schema_version") != "mcp.run/v1" or run.get("digest") != _digest(
        unsigned
    ):
        raise ValueError("Run digest mismatch")
    return {
        "schema_version": "mcp.run-inspection/v1",
        "run_id": run["run_id"],
        "status": run["status"],
        "target_id": run["target_id"],
        "run_digest": run["digest"],
        "candidate_artifact": run["result"],
        "provenance": {
            "accepted_plan_digest": run["accepted_plan_digest"],
            "acceptance_receipt": run["acceptance_receipt"],
        },
    }


def _inspect_run_reference(run_id):
    return _inspect_run(STATE.get(run_id, "run")["run"])


def _review_quality_plan(
    plan_id: str,
) -> dict[str, Any]:
    """Review a server-owned quality plan with the configured independent runtime."""

    plan = STATE.get(plan_id, "quality_plan")
    result = control_tools.review_quality_plan_tool(plan)
    return {
        **result,
        "quality_review_id": STATE.put("quality_review", result),
        "reviewed_plan_id": plan_id,
        "state_scope": "server_process",
    }


def _finalized_planner_receipt(planner_result: dict[str, Any]) -> dict[str, Any]:
    receipt = planner_result.get("planner_receipt")
    if not isinstance(receipt, dict):
        raise ValueError(
            "execution preparation requires a server-owned planner receipt"
        )
    if receipt.get("disposition") != "ready_for_delivery":
        refinement = receipt.get("workflow_refinement_cycle") or {}
        selected = (receipt.get("adjudication") or {}).get("selected") or {}
        if (
            planner_result.get("execution_ready") is not True
            or receipt.get("disposition") != "blocked_for_refinement"
            or refinement.get("pre_execution_ready") is not True
            or refinement.get("findings")
            or selected.get("id")
            != (planner_result.get("execution_target") or {}).get("id")
        ):
            raise ValueError("Planner result is not ready for execution")
        receipt = {
            **receipt,
            "execution_handoff": {"route_locked": True, "selected_target": selected},
        }
    handoff = receipt.get("execution_handoff") or receipt.get("delivery_handoff")
    if not isinstance(handoff, dict) or handoff.get("route_locked") is not True:
        raise ValueError("Planner execution route is not locked")
    outcome = receipt.get("outcome_quality_contract")
    delivery = receipt.get("delivery_quality_plan")
    if not all(
        isinstance(plan, dict)
        and plan.get("lifecycle") == "frozen"
        and plan.get("review_status") == "passed"
        for plan in (outcome, delivery)
    ):
        raise ValueError("both planner quality plans must be frozen and passed")
    return receipt


def _evaluate_and_release(
    plan: dict[str, Any],
    candidate_artifact: Any,
    criterion_results: list[dict[str, Any]] | None = None,
    evaluator: dict[str, Any] | None = None,
    producer_id: str | None = None,
    authorization: dict[str, Any] | None = None,
    result_attestation: dict[str, Any] | None = None,
    deterministic_receipts: list[dict[str, Any]] | None = None,
    anchor_manifest: dict[str, Any] | None = None,
    authorized_evidence: list[dict[str, Any]] | None = None,
    deterministic_results: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Assess one exact candidate and release it only when every gate passes."""

    if deterministic_results is not None:
        assessed = control_tools.assess_executed_quality_candidate_tool(
            plan,
            candidate_artifact,
            producer_id=producer_id,
            authorized_evidence=list(authorized_evidence or ()),
            deterministic_results=deterministic_results,
        )
    else:
        assessed = control_tools.assess_quality_candidate_tool(
            plan,
            candidate_artifact,
            criterion_results,
            evaluator=evaluator,
            producer_id=producer_id,
            authorization=authorization,
            result_attestation=result_attestation,
            deterministic_receipts=deterministic_receipts,
            anchor_manifest=anchor_manifest,
            authorized_evidence=authorized_evidence,
        )
    authorized = assessed.get("authorized_assessment")
    if not isinstance(authorized, dict) or not authorized:
        return {
            "schema_version": "mcp.evaluated-delivery/v1",
            "assessment": assessed,
            "decision": "inconclusive",
            "released_artifact": None,
            "candidate_withheld": True,
        }
    delivery = control_tools.decide_quality_delivery_tool(
        plan, authorized, candidate_artifact
    )
    return {
        **delivery,
        "schema_version": "mcp.evaluated-delivery/v1",
        "assessment": assessed,
        "release_receipt_schema": delivery["schema_version"],
    }


def _evaluate_release_reference(
    plan_id: str,
    run_id: str,
    producer_id: str | None = None,
    authorized_evidence: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Assess the server-owned run against its frozen delivery plan."""

    plan = STATE.get(plan_id, "quality_plan")
    if (
        plan.get("schema_version") != "lunar.planner.route-delivery-quality-plan/v1"
        or plan.get("lifecycle") != "frozen"
        or plan.get("review_status") != "passed"
    ):
        raise ValueError("delivery evaluation requires a frozen passed delivery plan")
    run_record = STATE.get(run_id, "run")
    inspected = _inspect_run(run_record["run"])
    run = run_record["run"]
    candidate = inspected["candidate_artifact"]
    planner_result = STATE.get(run_record["planner_result_id"], "planner_result")
    planner_receipt = _finalized_planner_receipt(planner_result)
    evidence = [dict(row) for row in (authorized_evidence or ())]
    if not any(row.get("source_id") for row in evidence):
        request_frame = planner_receipt.get("request_frame", {})
        request_authority = request_frame.get("authority", {})
        evidence.append(
            {
                "source_id": "authorized:request",
                "authorized_principal_ids": [
                    str(request_authority.get("principal") or "lunar-user")
                ],
                "content": str(request_frame.get("goal") or ""),
            }
        )
    execution_receipt = (
        candidate.get("execution_receipt", {}) if isinstance(candidate, dict) else {}
    )
    route_verified = bool(
        _target_is_bound_to_handoff(
            planner_receipt,
            str(run.get("target_id", "")),
            str(run.get("target_kind", "")),
        )
        and run.get("accepted_plan_digest")
        and execution_receipt.get("plan_digest") == run.get("accepted_plan_digest")
        and execution_receipt.get("fallback_used") is False
        and execution_receipt.get("mutation") is False
        and run.get("mutation") is False
        and run.get("status") == "success"
    )
    source_anchors = [str(row["source_id"]) for row in evidence if row.get("source_id")]
    deterministic_results = [
        {
            "criterion_id": str(criterion["criterion_id"]),
            "verdict": "pass" if route_verified else "inconclusive",
            "artifact_anchors": ["candidate:complete"],
            "source_anchors": source_anchors,
        }
        for criterion in plan.get("criteria", ())
        if criterion.get("evaluator_mode") in {"deterministic", "hybrid"}
    ]
    result = _evaluate_and_release(
        plan,
        candidate,
        producer_id=producer_id,
        authorized_evidence=evidence,
        deterministic_results=deterministic_results,
    )
    return {
        **result,
        "release_result_id": STATE.put("release_result", result),
        "evaluated_plan_id": plan_id,
        "evaluated_run_id": run_id,
        "state_scope": "server_process",
    }
