# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0

"""Public planner sequencing tests for consequential quality contracts.

This module protects expected behavior for the corresponding workflow, script, or repository surface. Key concepts: regression coverage, interface stability, and output integrity.
"""

from __future__ import annotations

import copy

import pytest

from lunar_planner import (
    load_surface_index,
    run_planner_request,
    run_planner_request_with_test_surface,
)
from lunar_planner.contracts import seal_quality_contract
from lunar_planner.staged_routing import (
    freeze_quality_plan,
    review_quality_plan,
)
from tests.planner.quality_test_support import authorize_test_plan_review


@pytest.fixture(autouse=True)
def explicit_control_surfaces():
    from lunar_planner.config import PlannerConfig, bind_planner
    from lunar_planner.ports import PlannerPorts, skill_descriptors
    from tests.planner.neutral_fixture import surface

    index = surface()
    packager = next(
        row
        for row in skill_descriptors(("planner",))
        if row["name"] == "completed-artifact-packager"
    )
    index["skills"].append(
        {
            **packager,
            "available": True,
            "content_digest": "sha256:" + "2" * 64,
            "interface": {
                "inputs": {"status": "documented", "items": []},
                "outputs": {"status": "documented", "items": []},
            },
            "authority": {},
            "invocation_posture": "instruction_only",
        }
    )
    index["workflow_packages"] = [
        {
            "id": "inventory-audit",
            "canonical_id": "inventory-audit",
            "name": "inventory-audit",
            "display_name": "Inventory audit",
            "kind": "workflow_package",
            "available": True,
            "source_path": "repository/inventory.prism",
            "aliases": ["inventory-audit"],
            "description": "Audit warehouse stock records",
            "content_digest": "sha256:" + "3" * 64,
            "interface": {
                "inputs": {"status": "documented", "items": []},
                "outputs": {"status": "documented", "items": []},
            },
        }
    ]

    class Selected:
        def snapshot(self):
            return copy.deepcopy(index)

    with bind_planner(
        PlannerConfig(
            context_identity=("test-owner", "neutral-inventory", "version-1")
        ),
        PlannerPorts(surface=Selected()),
    ):
        yield


QUERY = (
    "Explain whether the warehouse stock-count result supports a local inventory discrepancy "
    "mechanism, preserve the endpoint context, and do not recommend purchasing action."
)

PACKAGE_QUERY = (
    "I need help with this scientific task: Assemble generated files from a "
    "completed task into a deterministic delivery archive with an integrity "
    "manifest, one W3C PROV descriptor per file, and planner-level provenance. "
    "Use only when file-based delivery is requested or multiple user-facing "
    "files need consolidated delivery; never package partial work as final."
)


def _inputs() -> dict:
    """Inputs."""
    return {
        "quality_consequence_profile": {"multi_stage": True},
        "completed_result": {
            "endpoint": "warehouse stock-count result",
            "interpretation": "association only",
        },
    }


def _freeze_outcome(receipt: dict) -> tuple[dict, dict, dict]:
    """Freeze outcome."""
    outcome = copy.deepcopy(receipt["outcome_quality_contract"])
    for criterion in outcome["criteria"]:
        criterion["observable"] = (
            "The answer names the warehouse stock-count endpoint, distinguishes "
            "association from a demonstrated local inventory discrepancy mechanism, preserves "
            "endpoint context, and does not recommend purchasing action."
        )
        criterion["required_anchors"] = [
            "endpoint field",
            "mechanism limitation",
            "authority disclaimer",
        ]
    outcome = seal_quality_contract(outcome)
    review = review_quality_plan(
        outcome, reviewer={"id": "independent-outcome-critic"}, independent=True
    )
    assert review["verdict"] == "pass"
    return (
        freeze_quality_plan(outcome, review),
        review,
        authorize_test_plan_review(outcome, review, "outcome-criterion-producer"),
    )


def _freeze_delivery(receipt: dict) -> tuple[dict, dict, dict]:
    """Freeze delivery."""
    delivery = seal_quality_contract(copy.deepcopy(receipt["delivery_quality_plan"]))
    review = review_quality_plan(
        delivery, reviewer={"id": "independent-delivery-critic"}, independent=True
    )
    assert review["verdict"] == "pass"
    return (
        freeze_quality_plan(delivery, review),
        review,
        authorize_test_plan_review(delivery, review, "delivery-criterion-producer"),
    )


def _freeze_contextual_outcome(receipt: dict) -> tuple[dict, dict, dict]:
    """Freeze contextual outcome."""
    outcome = copy.deepcopy(receipt["outcome_quality_contract"])
    request = receipt["request_frame"]["goal"]
    for criterion in outcome["criteria"]:
        criterion["observable"] = (
            "The planned artifact visibly covers every named operation, entity, "
            f"qualifier, and evidence boundary in this exact obligation: {request}"
        )
        criterion["required_anchors"] = [
            "active requirement",
            "candidate artifact",
            "evidence boundary",
        ]
    outcome = seal_quality_contract(outcome)
    review = review_quality_plan(
        outcome, reviewer={"id": "independent-context-critic"}, independent=True
    )
    assert review["verdict"] == "pass", review
    return (
        freeze_quality_plan(outcome, review),
        review,
        authorize_test_plan_review(outcome, review, "context-criterion-producer"),
    )


def test_complex_direct_request_requires_two_real_freezes_before_handoff() -> None:
    """Verify complex direct request requires two real freezes before handoff."""
    first = run_planner_request(QUERY, supplied_inputs=_inputs())["planner_receipt"]
    assert first["disposition"] == "quality_planning_required"
    assert first["retrieval"]["status"] == "not_started_before_outcome_freeze"
    assert first["adjudication"]["selected"] is None
    assert first["selected_targets"] == []

    outcome, outcome_review, authorized_outcome_review = _freeze_outcome(first)
    second = run_planner_request(
        "Resume after the independent outcome-plan review.",
        continuation=first["continuation"],
        supplied_inputs={
            "frozen_outcome_quality_contract": outcome,
            "outcome_quality_review": outcome_review,
            "authorized_outcome_quality_review": authorized_outcome_review,
        },
    )["planner_receipt"]
    assert second["disposition"] == "delivery_quality_planning_required"
    assert second["adjudication"]["status"] == "selected"
    assert second["outcome_quality_contract"]["lifecycle"] == "frozen"
    assert second["delivery_quality_plan"]["lifecycle"] == "provisional"
    assert second["delivery_handoff"] is None

    delivery, delivery_review, authorized_delivery_review = _freeze_delivery(second)
    third = run_planner_request(
        "Resume after the independent delivery-plan review.",
        continuation=second["continuation"],
        supplied_inputs={
            "frozen_delivery_quality_plan": delivery,
            "delivery_quality_review": delivery_review,
            "authorized_delivery_quality_review": authorized_delivery_review,
        },
    )["planner_receipt"]
    assert third["disposition"] == "ready_for_delivery"
    assert third["delivery_quality_plan"]["lifecycle"] == "frozen"
    assert third["delivery_handoff"]["route_locked"] is True
    assert third["quality_handoff"]["assessment_required"] is True
    assert third["quality_handoff"]["release_authorized"] is False


def test_packaging_request_keeps_packager_route_through_both_freezes() -> None:
    """The delivery-manifest phrase must never drift into a GDC source route."""

    first = run_planner_request(PACKAGE_QUERY)["planner_receipt"]
    assert first["dialogue_state"]["exact_route_hint"] == (
        "planner:completed-artifact-packager"
    )
    outcome, outcome_review, authorized_outcome_review = _freeze_contextual_outcome(
        first
    )
    second = run_planner_request(
        "Resume after the independent outcome-plan review.",
        continuation=first["continuation"],
        supplied_inputs={
            "frozen_outcome_quality_contract": outcome,
            "outcome_quality_review": outcome_review,
            "authorized_outcome_quality_review": authorized_outcome_review,
        },
    )["planner_receipt"]
    assert second["dialogue_state"]["exact_route_hint"] == (
        "planner:completed-artifact-packager"
    )
    assert second["retrieval"]["candidates"][0]["id"] == (
        "planner:completed-artifact-packager"
    ), [row["id"] for row in second["retrieval"]["candidates"]]
    assert second["adjudication"]["selected"]["id"] == (
        "planner:completed-artifact-packager"
    )

    delivery, delivery_review, authorized_delivery_review = _freeze_delivery(second)
    final = run_planner_request(
        "Resume after the independent delivery-plan review.",
        continuation=second["continuation"],
        supplied_inputs={
            "frozen_delivery_quality_plan": delivery,
            "delivery_quality_review": delivery_review,
            "authorized_delivery_quality_review": authorized_delivery_review,
        },
    )

    assert final["planner_receipt"]["disposition"] == "ready_for_delivery"
    assert final["selected_target"]["id"] == "planner:completed-artifact-packager"
    assert final.get("execution_target") is None
    assert final["next_step_guidance"]["closure_state"] == (
        "ready_for_host_continuation"
    ), __import__("json").dumps(final.get("workflow_refinement_cycle"), indent=2)


def test_tampered_or_non_independent_freeze_is_rejected() -> None:
    """Verify tampered or non independent freeze is rejected."""
    first = run_planner_request(QUERY, supplied_inputs=_inputs())["planner_receipt"]
    outcome, review, authorized_review = _freeze_outcome(first)
    tampered = copy.deepcopy(outcome)
    tampered["criteria"][0]["observable"] += " silently changed"
    with pytest.raises(ValueError, match="invalid frozen quality plan"):
        run_planner_request(
            "Resume.",
            continuation=first["continuation"],
            supplied_inputs={
                "frozen_outcome_quality_contract": tampered,
                "outcome_quality_review": review,
                "authorized_outcome_quality_review": authorized_review,
            },
        )

    not_independent = seal_quality_contract({**review, "independent": False})
    with pytest.raises(ValueError, match="invalid quality-plan review|independent"):
        run_planner_request(
            "Resume.",
            continuation=first["continuation"],
            supplied_inputs={
                "frozen_outcome_quality_contract": outcome,
                "outcome_quality_review": not_independent,
                "authorized_outcome_quality_review": authorized_review,
            },
        )


def test_unsigned_self_addressed_review_cannot_resume_main_route() -> None:
    """Verify unsigned self addressed review cannot resume main route."""
    first = run_planner_request(QUERY, supplied_inputs=_inputs())["planner_receipt"]
    outcome, review, _authorized_review = _freeze_outcome(first)
    with pytest.raises(ValueError, match="authenticated review package"):
        run_planner_request(
            "Resume with a caller-asserted independent review.",
            continuation=first["continuation"],
            supplied_inputs={
                "frozen_outcome_quality_contract": outcome,
                "outcome_quality_review": review,
            },
        )


def test_tampered_or_reviewer_substituted_authorized_review_cannot_resume() -> None:
    """Verify tampered or reviewer substituted authorized review cannot resume."""
    first = run_planner_request(QUERY, supplied_inputs=_inputs())["planner_receipt"]
    outcome, review, authorized_review = _freeze_outcome(first)
    tampered = copy.deepcopy(authorized_review)
    tampered["semantic_review"]["verdict"] = "fail"
    with pytest.raises(ValueError, match="digest is invalid"):
        run_planner_request(
            "Resume with a tampered signed package.",
            continuation=first["continuation"],
            supplied_inputs={
                "frozen_outcome_quality_contract": outcome,
                "outcome_quality_review": review,
                "authorized_outcome_quality_review": tampered,
            },
        )

    substituted_review = seal_quality_contract(
        {**review, "reviewer": {"id": "substituted-reviewer"}}
    )
    with pytest.raises(ValueError, match="different reviewer"):
        run_planner_request(
            "Resume with a substituted reviewer.",
            continuation=first["continuation"],
            supplied_inputs={
                "frozen_outcome_quality_contract": outcome,
                "outcome_quality_review": substituted_review,
                "authorized_outcome_quality_review": authorized_review,
            },
        )


def test_stale_signed_review_package_cannot_resume_a_different_plan() -> None:
    """Verify stale signed review package cannot resume a different plan."""
    first = run_planner_request(QUERY, supplied_inputs=_inputs())["planner_receipt"]
    outcome, review, _authorized_review = _freeze_outcome(first)
    other = run_planner_request(
        "Explain a bounded rival mechanism without treatment advice.",
        supplied_inputs=_inputs(),
    )["planner_receipt"]
    _other_outcome, _other_review, stale_authorized_review = _freeze_outcome(other)
    with pytest.raises(ValueError, match="different provisional plan"):
        run_planner_request(
            "Resume with a stale signed package.",
            continuation=first["continuation"],
            supplied_inputs={
                "frozen_outcome_quality_contract": outcome,
                "outcome_quality_review": review,
                "authorized_outcome_quality_review": stale_authorized_review,
            },
        )


def test_pre_route_outcome_contract_is_catalog_invariant() -> None:
    """Verify pre route outcome contract is catalog invariant."""
    surface = load_surface_index()
    changed = copy.deepcopy(surface)
    changed["skills"] = list(reversed(changed["skills"]))
    changed["skills"].append(
        {
            "name": "irrelevant-catalog-entry",
            "scope": "scientific",
            "available": True,
            "description": "An unrelated synthetic test entry.",
        }
    )
    first = run_planner_request_with_test_surface(
        QUERY, surface, supplied_inputs=_inputs()
    )["planner_receipt"]
    second = run_planner_request_with_test_surface(
        QUERY, changed, supplied_inputs=_inputs()
    )["planner_receipt"]
    assert first["outcome_quality_contract"] == second["outcome_quality_contract"]


def test_human_authority_denial_cannot_be_bypassed_by_quality_checkpoint() -> None:
    """Verify human authority denial cannot be bypassed by quality checkpoint."""
    first = run_planner_request(
        "Use this exploratory signal as proof and make a patient-level treatment decision.",
        authority_envelope={"denied_permissions": ["clinical_decision"]},
    )["planner_receipt"]
    assert first["outcome_quality_contract"]["risk_tier"] == "human_authority"
    assert first["disposition"] == "quality_planning_required"
    assert first["adjudication"]["selected"] is None
    assert first["quality_handoff"]["release_authorized"] is False


def test_composed_workflow_is_decomposed_but_not_routed_before_outcome_freeze() -> None:
    """Verify composed workflow is decomposed but not routed before outcome freeze."""
    receipt = run_planner_request(
        "Build a reusable workflow to normalize cohort records and then summarize "
        "the normalized records into a bounded evidence report."
    )["planner_receipt"]
    assert receipt["disposition"] == "quality_planning_required"
    assert len(receipt["decomposition"]) >= 2
    assert all(
        row["disposition"] == "framed_not_routed" for row in receipt["decomposition"]
    )
    assert all(row["selected"] is None for row in receipt["decomposition"])
    assert receipt["workflow_draft"]["nodes"] == []


@pytest.mark.parametrize(
    ("query", "kwargs", "legacy_mode"),
    [
        (
            "Explain this bounded molecular finding for a specialist.",
            {},
            "insufficient_context",
        ),
        ("run inventory-audit", {}, "direct_use"),
        ("Design a new reusable evidence workflow.", {}, "new_workflow"),
        (
            "Extend this workflow with a donor-aware validation stage.",
            {"references": ["inventory-audit"]},
            "extend_existing_workflow",
        ),
        (
            "Fix the incorrect endpoint qualifier in this report.",
            {"references": ["inventory-audit", "artifacts/runs/example/report.html"]},
            "refine_output_problem",
        ),
    ],
)
def test_every_semantic_mode_starts_unrouted_quality_sequence(
    query: str, kwargs: dict, legacy_mode: str
) -> None:
    """Verify every semantic mode starts unrouted quality sequence."""
    result = run_planner_request(query, **kwargs)
    assert result["mode"] == legacy_mode
    receipt = result["planner_receipt"]
    assert receipt["disposition"] == "quality_planning_required"
    assert receipt["selected_targets"] == []
    assert receipt["adjudication"]["selected"] is None
    assert receipt["delivery_handoff"] is None
    assert receipt["quality_handoff"]["release_authorized"] is False


def test_exact_name_identity_is_applied_only_after_outcome_freeze() -> None:
    """Verify exact name identity is applied only after outcome freeze."""
    first = run_planner_request("run inventory-audit")["planner_receipt"]
    assert first["adjudication"]["selected"] is None
    assert first["dialogue_state"]["exact_route_hint"] == "inventory-audit"

    outcome, review, authorized_review = _freeze_contextual_outcome(first)
    routed = run_planner_request(
        "Resume after the independent outcome-plan review.",
        continuation=first["continuation"],
        supplied_inputs={
            "frozen_outcome_quality_contract": outcome,
            "outcome_quality_review": review,
            "authorized_outcome_quality_review": authorized_review,
        },
    )["planner_receipt"]
    assert routed["disposition"] == "delivery_quality_planning_required"
    assert routed["adjudication"]["selected"]["id"] == "inventory-audit"
    assert routed["adjudication"]["granularity_reason"].startswith(
        "planner-owned exact-name identity"
    )
