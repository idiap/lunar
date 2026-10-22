# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0

"""Context-specific quality contracts and non-compensatory release gates.

This module protects expected behavior for the corresponding workflow, script, or repository surface. Key concepts: regression coverage, interface stability, and output integrity.
"""

from __future__ import annotations

import copy

import pytest

from lunar_planner import (
    run_planner_request,
    run_planner_request_with_test_surface,
)
from lunar_planner.contracts import (
    seal_quality_contract,
    validate_contract,
    validate_quality_lineage_chain,
)
from lunar_planner.staged_routing import (
    assess_quality_artifact,
    build_quality_repair,
    decide_final_delivery,
    freeze_quality_plan,
    invalidate_quality_plan,
    review_quality_plan,
)
from tests.planner.quality_test_support import authorize_test_plan_review


def _quality_receipt() -> dict:
    """Quality receipt."""
    return run_planner_request(
        "Explain whether the warehouse stock-count result supports a local inventory discrepancy, preserve the endpoint context, and do not recommend purchasing action."
    )["planner_receipt"]


def _routed_quality_receipt() -> dict:
    """Routed quality receipt."""
    first = _quality_receipt()
    outcome = copy.deepcopy(first["outcome_quality_contract"])
    for row in outcome["criteria"]:
        if row["observable"].startswith("The artifact must expose"):
            row["observable"] = (
                "The explanation names the warehouse stock-count endpoint, "
                "separates association from a demonstrated local inventory discrepancy, "
                "preserves endpoint context, and does not recommend purchasing action."
            )
            row["required_anchors"] = [
                "endpoint field",
                "mechanism limitation",
                "authority disclaimer",
            ]
    outcome = seal_quality_contract(outcome)
    review = review_quality_plan(
        outcome, reviewer={"id": "external-criterion-reviewer"}, independent=True
    )
    assert review["verdict"] == "pass", review
    authorized_review = authorize_test_plan_review(
        outcome, review, "test-criterion-producer"
    )
    outcome = freeze_quality_plan(outcome, review)
    return run_planner_request(
        "Resume after the outcome-quality review.",
        continuation=first["continuation"],
        supplied_inputs={
            "frozen_outcome_quality_contract": outcome,
            "outcome_quality_review": review,
            "authorized_outcome_quality_review": authorized_review,
        },
    )["planner_receipt"]


def _passing_rows(plan: dict) -> list[dict]:
    """Passing rows."""
    return [
        {
            "criterion_id": row["criterion_id"],
            "verdict": "pass",
            "artifact_anchors": ["paragraph:1"],
            "source_anchors": ["request"],
            "uncertainty": "low",
        }
        for row in plan["criteria"]
    ]


def _frozen_delivery() -> dict:
    """Frozen delivery."""
    receipt = _routed_quality_receipt()
    plan = receipt["delivery_quality_plan"]
    review = review_quality_plan(
        plan, reviewer={"id": "external-criterion-reviewer"}, independent=True
    )
    assert review["verdict"] == "pass", review
    return freeze_quality_plan(plan, review)


def test_main_route_emits_pre_route_seeds_and_requires_independent_freeze() -> None:
    """Verify main route emits pre route seeds and requires independent freeze."""
    receipt = _quality_receipt()
    outcome = receipt["outcome_quality_contract"]

    assert outcome["lifecycle"] == "provisional"
    assert validate_contract(outcome).valid
    assert "selected_target" not in outcome
    assert receipt["delivery_quality_plan"] is None
    assert receipt["retrieval"]["status"] == "not_started_before_outcome_freeze"
    assert receipt["disposition"] == "quality_planning_required"

    routed = _routed_quality_receipt()
    delivery = routed["delivery_quality_plan"]
    assert delivery["lifecycle"] == "provisional"
    assert validate_contract(delivery).valid
    assert (
        delivery["outcome_contract_digest"]
        == routed["outcome_quality_contract"]["digest"]
    )
    assert {row["criterion_id"] for row in outcome["criteria"]} < {
        row["criterion_id"] for row in delivery["criteria"]
    }
    observable = " ".join(row["observable"] for row in outcome["criteria"])
    assert "stock-count" in observable
    assert "local inventory discrepancy" in observable
    assert receipt["quality_handoff"]["release_authorized"] is False
    assert routed["quality_handoff"]["independent_quality_validation_required"] is True
    assert receipt["outcome_quality_review"]["verdict"] != "pass"
    assert routed["disposition"] == "delivery_quality_planning_required"


def test_outcome_contract_is_catalog_invariant() -> None:
    """Verify outcome contract is catalog invariant."""
    first = run_planner_request("Explain why this source was excluded.")[
        "planner_receipt"
    ]
    second = run_planner_request("Explain why this source was excluded.")[
        "planner_receipt"
    ]
    assert (
        first["outcome_quality_contract"]["digest"]
        == second["outcome_quality_contract"]["digest"]
    )


def test_outcome_contract_is_invariant_to_a_changed_candidate_catalog() -> None:
    """A convenient route cannot redefine the pre-route outcome quality bar."""

    request = (
        "Explain the supplied endpoint while preserving the no-causal-claim boundary."
    )
    empty = {
        "schema_version": "lunar.planner.surface-index/v1",
        "skills": [],
        "workflow_packages": [],
        "subworkflows": [],
    }
    tempting = {
        **empty,
        "skills": [
            {
                "id": "scientific:causal-proof-shortcut",
                "name": "causal-proof-shortcut",
                "scope": "scientific",
                "description": "Conveniently turn endpoints into causal proof",
                "purpose": "Conveniently turn endpoints into causal proof",
                "triggers": "endpoint causal proof",
                "non_triggers": "",
                "source_path": "framework/causal-proof-shortcut/SKILL.md",
                "available": True,
                "invocation_posture": "instruction_only",
                "content_digest": "sha256:" + "0" * 64,
                "aliases": [],
                "interface": {
                    "inputs": {"status": "documented", "items": []},
                    "outputs": {"status": "documented", "items": []},
                },
                "authority": {},
            }
        ],
    }
    first = run_planner_request_with_test_surface(request, empty)["planner_receipt"]
    second = run_planner_request_with_test_surface(request, tempting)["planner_receipt"]

    left = first["outcome_quality_contract"]
    right = second["outcome_quality_contract"]
    # Run/snapshot lineage is intentionally different; the quality bar is not.
    for field in (
        "requirement_ids",
        "criteria",
        "criterion_consumer_trace",
        "evidence_whitelist",
        "risk_tier",
    ):
        assert left[field] == right[field]


def test_generic_or_tampered_quality_documents_fail_closed() -> None:
    """Verify generic or tampered quality documents fail closed."""
    outcome = _quality_receipt()["outcome_quality_contract"]
    generic = copy.deepcopy(outcome)
    generic["criteria"][0]["observable"] = "Accurate"
    assert any("generic-only" in error for error in validate_contract(generic).errors)

    tampered = copy.deepcopy(outcome)
    tampered["criteria"][0]["observable"] += " Changed after freeze."
    assert any(
        "digest does not match" in error for error in validate_contract(tampered).errors
    )


def test_exact_artifact_assessment_and_non_compensatory_decision() -> None:
    """Verify exact artifact assessment and non compensatory decision."""
    plan = _frozen_delivery()
    artifact = {"summary": "The result is associative, not purchasing action advice."}
    assessment = assess_quality_artifact(
        plan,
        artifact,
        _passing_rows(plan),
        evaluator={"id": "independent-evaluator", "configuration": "qc-v1"},
        producer_id="producer",
    )
    decision = decide_final_delivery(plan, assessment, artifact)
    assert assessment["verdict"] == "pass"
    assert decision["decision"] == "release"
    assert decision["presentable_as_user_answer"] is True

    changed = {"summary": artifact["summary"] + " Therefore choose therapy A."}
    blocked = decide_final_delivery(plan, assessment, changed)
    assert blocked["decision"] == "inconclusive"
    assert "artifact changed after assessment" in blocked["reasons"]


def test_self_review_and_missing_must_pass_result_cannot_release() -> None:
    """Verify self review and missing must pass result cannot release."""
    plan = _frozen_delivery()
    artifact = "bounded answer"
    rows = _passing_rows(plan)[1:]
    assessment = assess_quality_artifact(
        plan,
        artifact,
        rows,
        evaluator={"id": "same-producer"},
        producer_id="same-producer",
    )
    assert assessment["verdict"] == "inconclusive"
    assert (
        decide_final_delivery(plan, assessment, artifact)["decision"] == "inconclusive"
    )

    bad_rows = _passing_rows(plan)
    bad_rows[0]["artifact_digest"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError, match="assessed artifact digest"):
        assess_quality_artifact(
            plan,
            artifact,
            bad_rows,
            evaluator={"id": "independent"},
            producer_id="producer",
        )


def test_selective_invalidation_and_bounded_single_failure_repair() -> None:
    """Verify selective invalidation and bounded single failure repair."""
    plan = _frozen_delivery()
    revised = invalidate_quality_plan(plan, ["rendered artifact"], next_version=2)
    states = {row["criterion_id"]: row["lifecycle"] for row in revised["criteria"]}
    assert states["delivery-route-binding-integrity"] == "superseded"
    assert any(
        state == "frozen"
        for key, state in states.items()
        if key != "delivery-route-binding-integrity"
    )

    rows = _passing_rows(plan)
    rows[0]["verdict"] = "fail"
    assessment = assess_quality_artifact(
        plan, "candidate", rows, evaluator={"id": "critic"}, producer_id="producer"
    )
    repair = build_quality_repair(assessment)
    assert repair["status"] == "repair_required"
    assert len(repair["invalidate_criterion_ids"]) == 1
    assert repair["broad_rebuild_allowed"] is False
    exhausted = build_quality_repair(assessment, prior_attempts=2)
    assert exhausted["status"] == "blocked_attempts_exhausted"
    assert exhausted["automatic_repair_authorized"] is False


def test_internal_quality_roles_cannot_present_their_output() -> None:
    """Verify internal quality roles cannot present their output."""
    review = _routed_quality_receipt()["delivery_quality_review"]
    escalated = copy.deepcopy(review)
    escalated["presentable_as_user_answer"] = True
    assert any(
        "cannot be presented" in error for error in validate_contract(escalated).errors
    )


def test_quality_lineage_rejects_cycles_and_role_escalation() -> None:
    """Verify quality lineage rejects cycles and role escalation."""
    review = _routed_quality_receipt()["delivery_quality_review"]
    cycle = copy.deepcopy(review)
    cycle["parent_digest"] = cycle["digest"]
    assert validate_quality_lineage_chain([cycle]) == (
        "quality lineage contains a self-cycle",
        "quality lineage contains a cycle",
    )
    escalated = seal_quality_contract({**review, "operation_role": "final_delivery"})
    assert (
        "only a final-delivery-decision contract may use final_delivery role"
        in validate_quality_lineage_chain([escalated])
    )


def test_quality_schema_rejects_non_independent_passing_review() -> None:
    """Verify quality schema rejects non independent passing review."""
    review = _quality_receipt()["outcome_quality_review"]
    invalid = copy.deepcopy(review)
    invalid["verdict"] = "pass"
    invalid["independent"] = False
    invalid = seal_quality_contract(invalid)
    assert any(
        "must be independent" in error for error in validate_contract(invalid).errors
    )


@pytest.mark.parametrize(
    ("query", "kwargs", "expected_mode", "expected_status"),
    [
        ("List capabilities", {}, "capability_help", "complete"),
        (
            "Recommend a purchasing action and execute it for this patient",
            {
                "authority_envelope": {
                    "mode": "execution",
                    "requested_permissions": ["execute"],
                }
            },
            "insufficient_context",
            "denied",
        ),
    ],
)
def test_control_and_denied_routes_receive_quality_frame_without_catalog_routing(
    query: str, kwargs: dict, expected_mode: str, expected_status: str
) -> None:
    """Verify control and denied routes receive quality frame without catalog routing."""
    result = run_planner_request(query, **kwargs)
    assert result["mode"] == expected_mode
    assert result["status"] == expected_status
    receipt = result["planner_receipt"]
    assert receipt["control_route"] is True
    assert "retrieval" not in receipt
    assert receipt["request_frame"]["goal"] == query
    assert receipt["outcome_quality_contract"]["lifecycle"] == "frozen"
    assert receipt["delivery_quality_plan"]["lifecycle"] == "frozen"
    assert receipt["quality_handoff"]["release_authorized"] is (
        expected_status != "denied"
    )
    assert receipt["quality_handoff"]["semantic_payload_release_authorized"] is False
