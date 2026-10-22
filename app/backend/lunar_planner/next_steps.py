# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0

"""Closure-oriented next-step guidance for planner results.

This module is deliberately a projection over an existing planner result. It
does not continue planning, execute a component, request authority, or invent
optional work merely to keep a conversation active.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .portable import stable_hash

_OMIT_MODES = frozenset({"capability_help", "inspect_provenance"})
_CLOSED_STATUSES = frozenset({"complete", "accepted", "rejected"})


def _mapping(value: object) -> Mapping[str, Any]:
    """Mapping."""
    return value if isinstance(value, Mapping) else {}


def _sequence(value: object) -> Sequence[Any]:
    """Sequence."""
    return (
        value
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes))
        else ()
    )


def _source_state(result: Mapping[str, Any]) -> dict[str, Any]:
    """Source state."""
    receipt = _mapping(result.get("planner_receipt"))
    return {
        "mode": result.get("mode"),
        "status": result.get("status"),
        "blockers": list(_sequence(result.get("blockers"))),
        "receipt_digest": receipt.get("digest"),
        "disposition": receipt.get("disposition"),
        "selected_target": result.get("selected_target"),
        "delivery_handoff": result.get("delivery_handoff"),
    }


def assess_closure_readiness(planner_result: Mapping[str, Any]) -> dict[str, Any]:
    """Decide whether one evidenced closure dependency warrants a suggestion."""

    mode = str(planner_result.get("mode", ""))
    status = str(planner_result.get("status", ""))
    receipt = _mapping(planner_result.get("planner_receipt"))
    source_digest = stable_hash(_source_state(planner_result))

    if mode in _OMIT_MODES:
        return {
            "closure_state": (
                "closed" if status == "complete" else "non_planning_control"
            ),
            "disposition": "omit",
            "reason": "the current response is a control or informational operation, not an open planning step",
            "obligations": [],
            "source_state_digest": source_digest,
        }
    if status == "denied":
        return {
            "closure_state": "blocked",
            "disposition": "omit",
            "reason": "the request is denied; a suggestion cannot broaden authority or recast the denied action",
            "obligations": [],
            "source_state_digest": source_digest,
        }
    if status in _CLOSED_STATUSES:
        return {
            "closure_state": "closed",
            "disposition": "omit",
            "reason": "the planner state is already terminal",
            "obligations": [],
            "source_state_digest": source_digest,
        }

    elicitation = _mapping(planner_result.get("elicitation"))
    questions = list(_sequence(elicitation.get("questions")))
    blockers = [
        str(value)
        for value in _sequence(planner_result.get("blockers"))
        if str(value).strip()
    ]
    if status == "needs_input" and (questions or blockers or mode == "resume_plan"):
        obligation = (
            "question:"
            + str(_mapping(questions[0]).get("question_id", "material-input"))
            if questions
            else "input:planner-blocker"
        )
        return {
            "closure_state": "awaiting_input",
            "disposition": "suggest",
            "reason": "a named user input is required before the plan can advance",
            "obligations": [obligation],
            "source_state_digest": source_digest,
        }

    disposition = str(receipt.get("disposition", ""))
    quality_checkpoint = _mapping(receipt.get("quality_checkpoint"))
    if disposition in {
        "quality_planning_required",
        "delivery_quality_planning_required",
    }:
        checkpoint = (
            "delivery-quality-plan"
            if disposition.startswith("delivery")
            else "outcome-quality-contract"
        )
        return {
            "closure_state": "awaiting_review",
            "disposition": "suggest",
            "reason": "mandatory quality criteria exist but have not yet received the required independent review",
            "obligations": [f"review:{checkpoint}"],
            "source_state_digest": source_digest,
            "quality_checkpoint": quality_checkpoint,
        }

    refinement = _mapping(planner_result.get("workflow_refinement_cycle"))
    fix_plan = _mapping(refinement.get("fix_plan"))
    if fix_plan.get("status") == "required" and fix_plan.get("minimal_fix"):
        return {
            "closure_state": "repair_required",
            "disposition": "suggest",
            "reason": "the refinement cycle identifies an earliest localized failure with a bounded repair",
            "obligations": [f"repair:{fix_plan.get('diagnostic_target', 'workflow')}"],
            "source_state_digest": source_digest,
        }

    handoff = _mapping(planner_result.get("delivery_handoff"))
    if handoff:
        return {
            "closure_state": "ready_for_host_continuation",
            "disposition": "omit",
            "reason": "a route-locked handoff is ready for host inspection and preparation; execute_plan owns any required user approval",
            "obligations": [],
            "source_state_digest": source_digest,
        }

    if status == "ready_for_semantic_review" and planner_result.get("selected_target"):
        selected = _mapping(planner_result.get("selected_target"))
        target_id = str(selected.get("id", selected.get("name", "selected-target")))
        return {
            "closure_state": "awaiting_review",
            "disposition": "suggest",
            "reason": "one selected target remains subject to complete-body semantic review",
            "obligations": [f"semantic-review:{target_id}"],
            "source_state_digest": source_digest,
        }

    gap_plan = _mapping(planner_result.get("capability_gap_plan"))
    gaps = list(_sequence(gap_plan.get("gaps")))
    if status == "no_local_match" and gaps:
        gap_id = str(_mapping(gaps[0]).get("gap_id", "gap-1"))
        return {
            "closure_state": "gap_review_required",
            "disposition": "suggest",
            "reason": "an explicit capability gap must be accepted, revised, or rejected before implementation planning",
            "obligations": [f"gap-review:{gap_id}"],
            "source_state_digest": source_digest,
        }

    return {
        "closure_state": "open_without_actionable_target",
        "disposition": "omit",
        "reason": "no concrete unresolved obligation can be advanced without inventing optional work",
        "obligations": [],
        "source_state_digest": source_digest,
    }


def _suggestion(
    *,
    action: str,
    why_now: str,
    target_ids: Sequence[str],
    required_input: str,
    expected_artifact: str,
    completion_criterion: str,
    closes: str,
    authority: Mapping[str, Any],
    invocation: str | None = None,
) -> dict[str, Any]:
    """Suggestion."""
    core: dict[str, Any] = {
        "priority": 1,
        "action": action,
        "why_now": why_now,
        "target_ids": list(target_ids),
        "required_input": required_input,
        "expected_artifact": expected_artifact,
        "completion_criterion": completion_criterion,
        "closes": closes,
        "authority": dict(authority),
    }
    if invocation:
        core["planner_operation"] = invocation
    return {
        "suggestion_id": "next-step-" + stable_hash(core).split(":", 1)[1][:16],
        **core,
    }


def build_next_step_guidance(planner_result: Mapping[str, Any]) -> dict[str, Any]:
    """Return zero or one concrete suggestion aimed at planner closure."""

    assessment = assess_closure_readiness(planner_result)
    suggestions: list[dict[str, Any]] = []
    if assessment["disposition"] == "suggest":
        state = assessment["closure_state"]
        target = str(assessment["obligations"][0])
        receipt = _mapping(planner_result.get("planner_receipt"))
        if state == "awaiting_input":
            questions = list(
                _sequence(_mapping(planner_result.get("elicitation")).get("questions"))
            )
            question = _mapping(questions[0]) if questions else {}
            blockers = [
                str(value)
                for value in _sequence(planner_result.get("blockers"))
                if str(value).strip()
            ]
            requested = str(
                question.get(
                    "question",
                    question.get(
                        "text",
                        blockers[0] if blockers else "the active plan identifier",
                    ),
                )
            )
            suggestions.append(
                _suggestion(
                    action=f"Provide the missing planning input: {requested}",
                    why_now="the planner cannot bind or advance the route until this material input is explicit",
                    target_ids=[target],
                    required_input=requested,
                    expected_artifact="an updated continuation with the input bound to the active request",
                    completion_criterion="the next planner receipt no longer reports this input as unresolved",
                    closes=target,
                    authority={"required": "user_input", "side_effects": []},
                )
            )
        elif state == "awaiting_review" and target.startswith("review:"):
            checkpoint = _mapping(receipt.get("quality_checkpoint"))
            contract = _mapping(
                receipt.get(
                    "outcome_quality_contract", checkpoint.get("outcome_contract")
                )
            )
            plan = _mapping(
                receipt.get("delivery_quality_plan", checkpoint.get("delivery_plan"))
            )
            object_id = str(
                contract.get(
                    "contract_id", plan.get("plan_id", target.split(":", 1)[1])
                )
            )
            suggestions.append(
                _suggestion(
                    action=f"Independently review and freeze `{object_id}`.",
                    why_now="workflow selection and delivery remain blocked until the contextual criteria are reviewed",
                    target_ids=[object_id],
                    required_input="the exact provisional quality object and an independent reviewer decision",
                    expected_artifact="a digest-bound quality-plan review",
                    completion_criterion="review status is accepted and the next planner turn advances beyond the quality checkpoint",
                    closes=target,
                    authority={"required": "independent_review", "side_effects": []},
                    invocation="review_quality_plan",
                )
            )
        elif state == "repair_required":
            refinement = _mapping(planner_result.get("workflow_refinement_cycle"))
            fix = _mapping(refinement.get("fix_plan"))
            reruns = [
                str(value) for value in _sequence(fix.get("targeted_rerun_test_ids"))
            ]
            suggestions.append(
                _suggestion(
                    action=str(fix["minimal_fix"]),
                    why_now="this is the earliest diagnosed failure; later workflow work depends on it",
                    target_ids=[str(fix.get("diagnostic_target", "workflow")), *reruns],
                    required_input="implementation authorization and the failing artifact or binding",
                    expected_artifact="the minimally repaired component plus content-addressed rerun evidence",
                    completion_criterion="all targeted rerun tests pass while previously verified tests remain preserved",
                    closes=target,
                    authority={
                        "required": "separate_implementation_authorization",
                        "side_effects": [],
                    },
                )
            )
        elif state == "awaiting_review":
            selected = _mapping(planner_result.get("selected_target"))
            target_id = str(selected.get("id", selected.get("name", "selected-target")))
            suggestions.append(
                _suggestion(
                    action=f"Review the complete contract for `{target_id}` against the active requirement ledger.",
                    why_now="candidate retrieval is complete but semantic fit has not been accepted",
                    target_ids=[target_id],
                    required_input="the complete selected skill or workflow contract and active requirements",
                    expected_artifact="a semantic-fit decision with retained boundaries and blockers",
                    completion_criterion="the target is accepted, rejected, or returned with one material clarification",
                    closes=target,
                    authority={"required": "semantic_review", "side_effects": []},
                )
            )
        elif state == "gap_review_required":
            gap_id = target.split(":", 1)[1]
            suggestions.append(
                _suggestion(
                    action=f"Review capability gap `{gap_id}` and accept, revise, or reject its proposed contract.",
                    why_now="implementation planning cannot close while the residual capability need is unadjudicated",
                    target_ids=[gap_id],
                    required_input="the gap evidence, proposed ports, and reuse-search receipt",
                    expected_artifact="a governed gap disposition",
                    completion_criterion="the gap has an accepted reusable owner, an authorized proposal, or an explicit blocker",
                    closes=target,
                    authority={"required": "gap_review", "side_effects": []},
                )
            )

    result: dict[str, Any] = {
        "schema_version": "lunar.planner.next-step-guidance/v1",
        "closure_state": assessment["closure_state"],
        "disposition": assessment["disposition"],
        "reason": assessment["reason"],
        "source_state_digest": assessment["source_state_digest"],
        "skill_route": [
            "closure-readiness-assessor",
            *(["concrete-next-step-advisor"] if suggestions else []),
        ],
        "suggestions": suggestions,
    }
    result["digest"] = stable_hash(result)
    return result


__all__ = ["assess_closure_readiness", "build_next_step_guidance"]
