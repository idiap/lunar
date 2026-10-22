# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0

"""Deterministic two-freeze adapter for route-only planner benchmarks.

This module is evaluation infrastructure, not a production quality reviewer.
It lets routing benchmarks exercise the public universal state machine while
remaining explicit that they test harness conformance rather than biomedical
artifact correctness or release authorization.
"""

from __future__ import annotations

import copy
import os
from collections.abc import Callable, Mapping
from typing import Any

from .contracts import seal_quality_contract
from .quality_authorization import (
    attest_plan_review_result,
    issue_plan_review_authorization,
    verify_authorized_plan_review,
)
from .staged_routing import freeze_quality_plan, review_quality_plan

PlannerCall = Callable[..., dict[str, Any]]

# Public, benchmark-only trust material. This module is imported only by the
# route conformance runners and never by the production planner entrypoint.
_BENCHMARK_ONLY_QUALITY_KEY = "bioagents-route-benchmark-key-not-for-production"


def _call_with_benchmark_key(
    call_planner: PlannerCall, text: str, **values: Any
) -> dict[str, Any]:
    """Invoke one benchmark continuation without leaking trust state globally."""

    variable = "LUNAR_QUALITY_ATTESTATION_KEY"
    previous = os.environ.get(variable)
    os.environ[variable] = _BENCHMARK_ONLY_QUALITY_KEY
    try:
        return call_planner(text, **values)
    finally:
        if previous is None:
            os.environ.pop(variable, None)
        else:
            os.environ[variable] = previous


def _freeze_route_fixture(
    plan: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Freeze route fixture."""
    value = copy.deepcopy(dict(plan))
    for criterion in value.get("criteria", ()):
        if str(criterion.get("observable", "")).startswith("The artifact must expose"):
            criterion["observable"] = (
                "The route-only receipt visibly retains every named operation, entity, "
                "qualifier, requested artifact, and evidence boundary in the exact "
                "active requirement."
            )
            criterion["required_anchors"] = [
                "active requirement",
                "route-only receipt",
                "evidence boundary",
            ]
    value = seal_quality_contract(value)
    review = review_quality_plan(
        value,
        reviewer={"id": "benchmark-route-only-deterministic-critic"},
        independent=True,
    )
    if review.get("verdict") != "pass":
        raise ValueError(f"benchmark quality fixture failed adequacy lint: {review}")
    trusted_key = _BENCHMARK_ONLY_QUALITY_KEY.encode()
    reviewer = dict(review["reviewer"])
    producer_id = "benchmark-route-only-criterion-producer"
    semantic_review = {
        "plan_digest": value["digest"],
        "verdict": review["verdict"],
        "independent": review["independent"],
        "reviewer_id": reviewer["id"],
        "checks": review.get("checks", {}),
        "findings": review.get("findings", []),
        "evaluation_receipts": [
            {
                "phase": "plan_review",
                "request_digest": value["digest"],
                "status": review["verdict"],
                "evaluator": reviewer,
            }
            for _index in range(
                2 if value.get("risk_tier") in {"complex", "human_authority"} else 1
            )
        ],
    }
    authorization = issue_plan_review_authorization(
        value,
        reviewer=reviewer,
        criterion_producer_id=producer_id,
        nonce=f"route-fixture-{value['digest'][-12:]}",
        trusted_key=trusted_key,
    )
    attestation = attest_plan_review_result(
        authorization, semantic_review, trusted_key=trusted_key
    )
    authorized_review = verify_authorized_plan_review(
        value,
        semantic_review,
        reviewer=reviewer,
        criterion_producer_id=producer_id,
        authorization=authorization,
        result_attestation=attestation,
        trusted_key=trusted_key,
    )
    return freeze_quality_plan(value, review), review, authorized_review


def drive_route_only_quality_protocol(
    first: Mapping[str, Any],
    *,
    call_planner: PlannerCall,
) -> dict[str, Any]:
    """Drive both reviewed freezes without claiming semantic certification."""

    original = dict(first)
    result = dict(first)
    receipt = result.get("planner_receipt")
    if not isinstance(receipt, Mapping) or receipt.get("control_route"):
        return result
    if receipt.get("disposition") != "quality_planning_required":
        return result
    outcome, outcome_review, authorized_outcome_review = _freeze_route_fixture(
        receipt["outcome_quality_contract"]
    )
    result = _call_with_benchmark_key(
        call_planner,
        "Resume the route-only benchmark fixture after outcome-quality review.",
        continuation=receipt["continuation"],
        supplied_inputs={
            "frozen_outcome_quality_contract": outcome,
            "outcome_quality_review": outcome_review,
            "authorized_outcome_quality_review": authorized_outcome_review,
        },
    )
    routed = result["planner_receipt"]
    if routed.get("disposition") != "delivery_quality_planning_required":
        merged = {**original, "planner_receipt": routed}
        merged["quality_disposition"] = routed.get("quality_disposition")
        return merged
    delivery, delivery_review, authorized_delivery_review = _freeze_route_fixture(
        routed["delivery_quality_plan"]
    )
    final = _call_with_benchmark_key(
        call_planner,
        "Resume the route-only benchmark fixture after delivery-quality review.",
        continuation=routed["continuation"],
        supplied_inputs={
            "frozen_delivery_quality_plan": delivery,
            "delivery_quality_review": delivery_review,
            "authorized_delivery_quality_review": authorized_delivery_review,
        },
    )
    final_receipt = final["planner_receipt"]
    # Preserve the benchmark's original legacy routing projection (candidate
    # cascade and resource scan) while replacing its formerly one-turn staged
    # receipt with the universally frozen receipt.  This is an evaluation
    # projection only; it does not authorize artifact release.
    merged = {**original, "planner_receipt": final_receipt}
    merged["quality_disposition"] = final_receipt.get("quality_disposition")
    merged["selected_targets"] = final_receipt.get("selected_targets", [])
    merged["dialogue_state"] = final_receipt.get("dialogue_state")
    selected = final_receipt.get("adjudication", {}).get("selected")
    if (
        selected is not None
        and merged.get("selected_target") is None
        and original.get("status") != "needs_input"
    ):
        merged["selected_target"] = selected
    disposition = final_receipt.get("disposition")
    specialized_domain_route = any(
        key in original
        for key in (
            "pharmaceutical_process_plan",
            "pharmaceutical_regulatory_reporting_plan",
        )
    )
    workflow_planning_mode = original.get("mode") in {
        "new_workflow",
        "extend_existing_workflow",
        "refine_output_problem",
    }
    if specialized_domain_route:
        # Domain planners already emitted an exact deterministic route/status.
        # The benchmark drives quality freezes to exercise the universal state
        # machine, not to replace that compatibility projection with a generic
        # catalog candidate selected from the synthetic continuation text.
        merged["status"] = original["status"]
    elif original.get("status") == "needs_input":
        merged["status"] = "needs_input"
    elif workflow_planning_mode and not (
        disposition == "blocked"
        and final_receipt.get("preflight", {}).get("authority_status") == "denied"
    ):
        merged["status"] = "ready_for_semantic_review"
    elif disposition == "ready_for_delivery":
        merged["status"] = "ready_for_semantic_review"
    elif disposition == "clarification_required":
        merged["status"] = "needs_input"
    elif disposition == "blocked":
        merged["status"] = "denied"
    return merged
