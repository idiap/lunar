# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
from pathlib import Path
from typing import Annotated, Any, Literal

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from state import STATE

REPO_ROOT = Path(__file__).resolve().parents[2]


def _plan_request(
    command_text: str,
    references: list[str] | None = None,
    desired_inputs: list[str] | None = None,
    desired_outputs: list[str] | None = None,
    supplied_inputs: dict[str, Any] | None = None,
    continuation_id: str | None = None,
    quality_review_id: str | None = None,
    scope: Literal["package", "all"] = "package",
    active_plan_id: str | None = None,
) -> dict[str, Any]:
    """Private planning-only engine boundary with server-owned review receipts."""
    from domain_packages.selection import CURRENT_VERSION, SELECTION_MESSAGE

    context = CURRENT_VERSION.get()
    if context is None:
        return {
            "planner_receipt": {"disposition": "selection_required"},
            "blockers": [SELECTION_MESSAGE],
        }
    from lunar_planner.config import current_config

    identity = tuple(
        str(value)
        for value in (context.user_id, context.package_id, context.version_id)
    )
    if current_config().context_identity != identity:
        return {
            "planner_receipt": {"disposition": "selection_required"},
            "blockers": ["Bind the owned package catalog before planning"],
        }
    from lunar_planner.entrypoint import (
        run_planner_request,
    )

    continuation = (
        STATE.get(continuation_id, "continuation") if continuation_id else None
    )
    inputs = dict(supplied_inputs or {})
    reserved_quality_inputs = {
        "frozen_outcome_quality_contract",
        "outcome_quality_review",
        "authorized_outcome_quality_review",
        "frozen_delivery_quality_plan",
        "delivery_quality_review",
        "authorized_delivery_quality_review",
    }
    if reserved_quality_inputs.intersection(inputs):
        raise ValueError(
            "quality receipts must be supplied by opaque quality_review_id, not caller data"
        )
    if quality_review_id:
        if not continuation_id:
            raise ValueError("quality_review_id requires the prior continuation_id")
        reviewed = STATE.get(quality_review_id, "quality_review")
        frozen = reviewed.get("frozen_plan")
        if not frozen or reviewed.get("authorized_semantic_review") is None:
            raise ValueError("quality review is not frozen and authorized")
        schema = str(frozen.get("schema_version", ""))
        if "outcome-quality-contract" in schema:
            inputs.update(
                {
                    "frozen_outcome_quality_contract": frozen,
                    "outcome_quality_review": reviewed["review"],
                    "authorized_outcome_quality_review": reviewed[
                        "authorized_semantic_review"
                    ],
                }
            )
        elif "delivery-quality-plan" in schema:
            inputs.update(
                {
                    "frozen_delivery_quality_plan": frozen,
                    "delivery_quality_review": reviewed["review"],
                    "authorized_delivery_quality_review": reviewed[
                        "authorized_semantic_review"
                    ],
                }
            )
        else:
            raise ValueError("quality_review_id has an unsupported plan schema")

    result = run_planner_request(
        command_text,
        references=references,
        desired_inputs=desired_inputs or (),
        desired_outputs=desired_outputs or (),
        supplied_inputs=inputs or None,
        continuation=continuation,
        scope=scope,
        active_plan_id=active_plan_id,
        execution_mode="route_only",
        authority_envelope={
            "principal": str(context.user_id),
            "mode": "planning_only",
            "execution": "forbidden",
            "external_actions": "forbidden",
            "mutation": "forbidden",
        },
    )
    receipt = result.get("planner_receipt", {})
    refinement = receipt.get("workflow_refinement_cycle") or {}
    execution_ready = (
        receipt.get("disposition") == "blocked_for_refinement"
        and refinement.get("pre_execution_ready") is True
        and not refinement.get("findings")
    )
    if (
        receipt.get("disposition") == "ready_for_delivery" or execution_ready
    ) and not result.get("execution_target"):
        from lunar_planner.ports import current_ports

        locked = (
            (receipt.get("delivery_handoff") or {}).get("selected_target")
            or (receipt.get("adjudication") or {}).get("selected")
            or {}
        )
        surface = current_ports().surface
        registered = (
            next(
                (
                    row
                    for row in surface.snapshot()["workflow_packages"]
                    if row["id"] == locked.get("id")
                ),
                None,
            )
            if surface is not None
            else None
        )
        plans = [
            receipt.get("outcome_quality_contract") or {},
            receipt.get("delivery_quality_plan") or {},
        ]
        if registered and all(
            plan.get("lifecycle") == "frozen" and plan.get("review_status") == "passed"
            for plan in plans
        ):
            result["execution_target"] = {
                "id": registered["id"],
                "kind": registered["kind"],
                "operation": "run",
            }
            result["execution_ready"] = True
    next_continuation = receipt.get("continuation")
    disposition = receipt.get("disposition")
    reviewable_plan = None
    if disposition == "quality_planning_required":
        reviewable_plan = receipt.get("outcome_quality_contract")
    elif (
        disposition in {"delivery_quality_planning_required", "ready_for_delivery"}
        or result.get("execution_ready") is True
    ):
        reviewable_plan = receipt.get("delivery_quality_plan")
    return {
        **result,
        "planner_result_id": STATE.put("planner_result", result),
        "continuation_id": (
            STATE.put("continuation", next_continuation) if next_continuation else None
        ),
        "quality_plan_id": (
            STATE.put("quality_plan", reviewable_plan) if reviewable_plan else None
        ),
        "state_scope": "server_process",
    }


async def run_pipeline(
    request, *, principal=None, channel="stdio", observe=None, planning_only=None
):
    """Bind the owned catalog and policy worker for the entire invocation."""
    from domain_packages.context import CURRENT_VERSION, require_context
    from domain_packages.planning import planner_binding
    from domain_packages.routes import configured_storage
    from lunar_planner.config import bind_planner
    from modules.common import connect
    from planner_contract import PlannerResult, PlannerReasoning
    from uuid import UUID, uuid4

    try:
        if CURRENT_VERSION.get() is None:
            return PlannerResult(
                status="blocked",
                blockers=["Import and select a package version before planning."],
                reasoning=PlannerReasoning(run_id=uuid4(), state="blocked"),
            ).model_dump(mode="json")
        context = require_context(UUID(principal) if principal else None)
        connection = await connect()
        try:
            config, ports = await planner_binding(
                connection, context, configured_storage()
            )
        finally:
            await connection.close()
        with bind_planner(config, ports):
            return await _run_pipeline(
                request,
                principal=principal,
                channel=channel,
                observe=observe,
                planning_only=planning_only,
            )
    except Exception as error:
        return PlannerResult(
            status="failed",
            blockers=[str(error)[:2000]],
            reasoning=PlannerReasoning(run_id=uuid4(), state="failed"),
        ).model_dump(mode="json")


async def _run_pipeline(
    request, *, principal=None, channel="stdio", observe=None, planning_only=None
):
    """Own every lifecycle transition; clients resume only input clarification."""
    import asyncio
    import json
    import inspect
    from datetime import datetime, timezone
    from uuid import uuid4

    def stages():
        import scientific_tools

        return scientific_tools

    from planner_contract import PlannerInput, PlannerReasoning, PlannerResult
    from prism_runs.reasoning import (
        ReasoningEntry,
        Presentation,
        project_source,
        source_digest,
    )
    from reports import _publish_released_artifact
    from modules.chat import _planning_only_boundary_requested

    request = PlannerInput.model_validate(request)
    invocation = uuid4()
    entries = []
    presentations = []
    execution_status: Literal[
        "not_started", "completed", "handoff", "blocked", "failed"
    ] = "not_started"

    async def snapshot(
        state: Literal["running", "completed", "failed", "blocked"] = "running",
    ):
        value = PlannerReasoning(run_id=invocation, state=state, entries=entries)
        if observe:
            await observe(value.model_dump(mode="json"))
        return value

    async def present(entry):
        from prism_runs.reasoning_provider import generate_presentation

        digest = entry.source_digest
        presentation = await generate_presentation(entry.source)
        if entry.source_digest == digest:
            entry.presentation = presentation
            await snapshot()

    def add_entry(name, source):
        entry = ReasoningEntry(
            id=uuid4(),
            run_id=invocation,
            sequence=len(entries) + 1,
            source_event_key=f"{name}:{len(entries)+1}",
            event_kind="stage",
            observed_at=datetime.now(timezone.utc),
            source=source,
            source_digest=source_digest(source),
        )
        entries.append(entry)
        return entry

    def recorded_sources(result):
        from platform_runtime.reasoning_log import validate_reasoning_log
        from prism_runs.reasoning import public_text
        import re

        if not isinstance(result, dict):
            return
        # Only documented public logs, never arbitrary nested provider payloads.
        containers = [result] + [
            result[key]
            for key in ("planner_receipt", "assessment", "candidate_artifact")
            if isinstance(result.get(key), dict)
        ]
        seen_logs = set()
        for container in containers:
            log = container.get("reasoning_log")
            if not isinstance(log, dict) or log.get("digest") in seen_logs:
                continue
            validate_reasoning_log(log)
            seen_logs.add(log["digest"])
            for row in log["entries"]:
                decision = row["decision"]
                status: Literal["accepted", "rejected", "interrupted", "completed"]
                if decision["status"] == "accepted":
                    status = "accepted"
                elif decision["status"] == "rejected":
                    status = "rejected"
                elif decision["status"] == "blocked":
                    status = "interrupted"
                else:
                    status = "completed"
                references = [
                    value
                    for value in row.get("inputs_used", [])
                    if re.fullmatch(
                        r"(?:effect|source|artifact):[a-zA-Z0-9_.:-]{1,160}|sha256:[0-9a-f]{64}",
                        value,
                    )
                ]
                details = {
                    "summary": row["action"],
                    "rationale_summary": row["rationale_summary"],
                    "limitations": [
                        *log.get("limitations", []),
                        *row.get("blockers", []),
                        *row.get("checks", []),
                    ],
                }
                yield project_source(
                    stage=public_text(row["stage"]) or "recorded_decision",
                    status=status,
                    result=details,
                    evidence_references=references,
                )

    async def stage(name, function, *args, **kwargs):
        entry = add_entry(name, project_source(stage=name, status="running"))
        await snapshot()
        presentations.append(asyncio.create_task(present(entry)))
        try:
            result = (
                await function(*args, **kwargs)
                if inspect.iscoroutinefunction(function)
                else await asyncio.to_thread(function, *args, **kwargs)
            )
        except Exception:
            entry.source = project_source(stage=name, status="failed")
            entry.source_digest = source_digest(entry.source)
            entry.presentation = Presentation()
            presentations.append(asyncio.create_task(present(entry)))
            await snapshot()
            raise
        entry.source = project_source(stage=name, status="completed", result=result)
        entry.source_digest = source_digest(entry.source)
        entry.presentation = Presentation()
        await snapshot()
        presentations.append(asyncio.create_task(present(entry)))
        for source in recorded_sources(result):
            recorded = add_entry(name, source)
            await snapshot()
            presentations.append(asyncio.create_task(present(recorded)))
        return result

    def reasons(values, fallback):
        return [
            value[:2000]
            for value in (values or [])
            if isinstance(value, str) and value.strip()
        ][:10] or [fallback]

    async def finish(
        status: Literal[
            "completed", "planning_only", "clarification_required", "blocked", "failed"
        ],
        **kwargs: Any,
    ):
        await asyncio.gather(*presentations)
        state = (
            "failed"
            if status == "failed"
            else (
                "blocked"
                if status in {"blocked", "clarification_required"}
                else "completed"
            )
        )
        return PlannerResult(
            status=status,
            execution_status=execution_status,
            reasoning=await snapshot(state),
            **kwargs,
        ).model_dump(mode="json")

    try:
        arguments = request.model_dump(exclude_none=True, exclude={"ai_model_id"})
        original_request = request.command_text
        known_inputs = dict(request.supplied_inputs or {})
        planning_only = (
            planning_only
            if planning_only is not None
            else _planning_only_boundary_requested(
                [{"role": "user", "content": request.command_text}]
            )
        )
        if request.continuation_id:
            saved = STATE.get(request.continuation_id, "planner_clarification")
            if saved["principal"] != principal or saved["channel"] != channel:
                raise ValueError(
                    "clarification belongs to another principal or transport"
                )
            arguments["continuation_id"] = saved["continuation_id"]
            planning_only = saved["planning_only"]
            original_request = saved["original_request"]
            known_inputs = {**saved["supplied_inputs"], **known_inputs}
        seen = set()
        for cycle in range(8):
            planned = await stage("planning", _plan_request, **arguments)
            receipt = planned.get("planner_receipt", {})
            disposition = receipt.get("disposition")
            fingerprint = json.dumps(
                {
                    "disposition": disposition,
                    "plan": receipt.get("delivery_quality_plan"),
                    "outcome": receipt.get("outcome_quality_contract"),
                    "questions": receipt.get("elicitation"),
                },
                sort_keys=True,
            )
            if fingerprint in seen:
                return await finish("blocked", blockers=["Planning made no progress."])
            seen.add(fingerprint)
            if disposition in {
                "quality_planning_required",
                "delivery_quality_planning_required",
            }:
                review = await stage(
                    "quality_review",
                    stages()._review_quality_plan,
                    planned["quality_plan_id"],
                )
                if review.get("review", {}).get("verdict") != "pass" or not review.get(
                    "authorized_semantic_review"
                ):
                    return await finish(
                        "blocked",
                        blockers=reasons(
                            review.get("review", {}).get("findings"),
                            "Quality review was rejected or unavailable.",
                        ),
                    )
                arguments = {
                    "command_text": "Resume after quality review.",
                    "continuation_id": planned["continuation_id"],
                    "quality_review_id": review["quality_review_id"],
                }
                continue
            if (
                disposition == "ready_for_delivery"
                or planned.get("execution_ready") is True
            ):
                break
            questions = (
                receipt.get("elicitation") or planned.get("elicitation") or {}
            ).get("questions", [])
            if not questions:
                dialogue = (receipt.get("continuation") or {}).get("dialogue_state", {})
                questions = [
                    row
                    for row in dialogue.get("question_history", [])
                    if row.get("status") == "open"
                ]
            if questions and planned.get("continuation_id"):
                continuation = STATE.put(
                    "planner_clarification",
                    {
                        "continuation_id": planned["continuation_id"],
                        "principal": principal,
                        "channel": channel,
                        "planning_only": planning_only,
                        "original_request": original_request,
                        "supplied_inputs": known_inputs,
                    },
                )
                return await finish(
                    "clarification_required",
                    questions=questions,
                    continuation_id=continuation,
                )
            return await finish(
                "blocked",
                blockers=[str(x)[:2000] for x in planned.get("blockers", [])][:10]
                or [
                    str(disposition or "Planning did not produce an executable route.")
                ],
            )
        else:
            return await finish(
                "blocked", blockers=["Planning exceeded the bounded review limit."]
            )
        if planning_only:
            return await finish(
                "planning_only",
                plan={
                    "goal": receipt.get("request_frame", {}).get(
                        "goal", original_request
                    ),
                    "execution_target": planned.get("execution_target"),
                    "selected_targets": receipt.get("selected_targets", []),
                    "disposition": receipt.get("disposition"),
                },
            )
        target = planned.get("execution_target")
        if not target:
            return await finish(
                "blocked", blockers=["No supported execution target was selected."]
            )
        await stage(
            "capability_inspection",
            stages()._inspect_capability,
            component_ids=[target["id"]],
            kinds=[target["kind"]],
            include=["contract", "availability"],
            planner_receipt_digest=receipt.get("digest"),
        )
        prepared = await stage(
            "preparation",
            stages()._prepare_execution_reference,
            planned["planner_result_id"],
            target_id=target["id"],
            target_kind=target["kind"],
            operation=target.get("operation"),
            principal=principal or "anonymous",
            supplied_inputs=known_inputs or None,
            ai_model_id=request.ai_model_id,
        )
        if prepared["status"] not in {"ready_for_acceptance", "ready_for_host"}:
            execution_status = "blocked"
            return await finish(
                "blocked",
                blockers=reasons(
                    prepared.get("preflight", {}).get("blockers"),
                    "Execution preflight blocked the selected target.",
                ),
                plan={"preflight": prepared.get("preflight", {})},
            )
        execution_status = "failed"
        run = await stage(
            "execution",
            stages().execute_prepared_reference,
            prepared["prepared_execution_id"],
            channel=channel,
        )
        inspected = await stage(
            "run_inspection", stages()._inspect_run_reference, run["run_id"]
        )
        if run["status"] == "host_action_required":
            execution_status = "handoff"
            return await finish(
                "blocked",
                blockers=[
                    "The selected target requires host execution; only instructions are available."
                ],
                plan={
                    "instruction_packet": inspected.get("candidate_artifact", {}).get(
                        "instruction_packet"
                    )
                },
            )
        if run["status"] not in {"success", "completed"}:
            return await finish(
                "failed", blockers=[f"Execution ended with status {run['status']}."]
            )
        execution_status = "completed"
        released = await stage(
            "delivery_evaluation",
            stages()._evaluate_release_reference,
            planned["quality_plan_id"],
            run["run_id"],
        )
        if (
            released.get("candidate_withheld") is not False
            or released.get("released_artifact") is None
        ):
            return await finish(
                "blocked",
                blockers=reasons(
                    released.get("quality_summary", {}).get("decision_reasons"),
                    "Delivery quality gate withheld the candidate artifact.",
                ),
            )
        artifact = released["released_artifact"]
        if principal is None:
            return await finish(
                "completed",
                released_artifact=artifact,
                publication="unavailable",
                publication_error="Publication requires an authenticated user; local stdio has no publication identity.",
            )
        try:
            report = await stage(
                "publication",
                _publish_released_artifact,
                released["release_result_id"],
                original_request[:200],
                principal,
            )
        except Exception as error:
            return await finish(
                "completed",
                released_artifact=artifact,
                publication="failed",
                publication_error=str(error)[:2000],
            )
        return await finish(
            "completed",
            released_artifact=artifact,
            report=report,
            publication="published",
        )
    except Exception as error:
        return await finish("failed", blockers=[str(error)[:2000]])


async def planner(
    command_text: Annotated[
        str,
        Field(
            min_length=1,
            description="The user's natural-language request for this turn.",
        ),
    ],
    ai_model_id: str | None = None,
    references: list[str] | None = None,
    desired_inputs: list[str] | None = None,
    desired_outputs: list[str] | None = None,
    supplied_inputs: Annotated[
        dict[str, Any] | None,
        Field(
            description="Known facts; use the returned questions' missing_fields keys for clarification."
        ),
    ] = None,
    continuation_id: Annotated[
        str | None,
        Field(description="The opaque continuation_id returned for clarification."),
    ] = None,
) -> dict[str, Any]:
    """Automatically plan, review, execute supported work, release and publish its result.

    Return recorded reasoning, the exact released artifact and any report reference.
    Ask returned clarification questions and resume with new facts and continuation_id.
    Explicit planning-only requests do not execute. Unsupported work remains blocked.
    Local stdio returns released artifacts with publication unavailable.
    """
    from mcp.server.auth.middleware.auth_context import get_access_token

    token = get_access_token()
    principal = token.subject if token else None
    return await run_pipeline(
        dict(
            command_text=command_text,
            references=references,
            desired_inputs=desired_inputs,
            desired_outputs=desired_outputs,
            supplied_inputs=supplied_inputs,
            continuation_id=continuation_id,
            ai_model_id=ai_model_id,
        ),
        principal=principal,
        channel="http" if token else "stdio",
    )


def register_planner_tool(mcp: FastMCP) -> None:
    mcp.tool(name="planner")(planner)
    tool = mcp._tool_manager.get_tool("planner")
    if tool is None:
        raise RuntimeError("planner tool registration failed")
    tool.fn_metadata.arg_model.model_config["extra"] = "forbid"
    tool.fn_metadata.arg_model.model_rebuild(force=True)
    tool.parameters = tool.fn_metadata.arg_model.model_json_schema()
