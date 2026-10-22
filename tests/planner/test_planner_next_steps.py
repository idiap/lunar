# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0

"""Closure-oriented planner next-step guidance regressions.

This module protects expected behavior for the corresponding workflow, script, or repository surface. Key concepts: regression coverage, interface stability, and output integrity.
"""

from __future__ import annotations

from lunar_planner.contracts import require_valid_contract
from lunar_planner.entrypoint import run_planner_request
from lunar_planner.next_steps import build_next_step_guidance


def test_quality_checkpoint_names_one_review_that_advances_closure() -> None:
    """Verify quality checkpoint names one review that advances closure."""
    result = run_planner_request("design a new inventory reconciliation workflow")
    guidance = result["next_step_guidance"]

    assert guidance["disposition"] == "suggest"
    assert guidance["closure_state"] == "awaiting_review"
    assert guidance["skill_route"] == [
        "closure-readiness-assessor",
        "concrete-next-step-advisor",
    ]
    assert len(guidance["suggestions"]) == 1
    suggestion = guidance["suggestions"][0]
    contract_id = result["planner_receipt"]["outcome_quality_contract"]["contract_id"]
    assert contract_id in suggestion["action"]
    assert suggestion["planner_operation"] == "review_quality_plan"
    assert suggestion["authority"]["required"] == "independent_review"
    assert "accepted" in suggestion["completion_criterion"]
    require_valid_contract(guidance)


def test_missing_intent_produces_one_concrete_input_request() -> None:
    """Verify missing intent produces one concrete input request."""
    result = run_planner_request("something")
    guidance = result["next_step_guidance"]

    assert guidance["closure_state"] == "awaiting_input"
    assert guidance["disposition"] == "suggest"
    assert len(guidance["suggestions"]) == 1
    suggestion = guidance["suggestions"][0]
    assert result["blockers"][0] in suggestion["action"]
    assert suggestion["authority"] == {"required": "user_input", "side_effects": []}
    assert suggestion["closes"] == "input:planner-blocker"


def test_complete_and_nonplanning_control_responses_do_not_upsell() -> None:
    """Verify complete and nonplanning control responses do not upsell."""
    help_guidance = run_planner_request("show capabilities")["next_step_guidance"]
    provenance_guidance = run_planner_request("inspect provenance")[
        "next_step_guidance"
    ]

    assert help_guidance["closure_state"] == "closed"
    assert provenance_guidance["closure_state"] == "non_planning_control"
    for guidance in (help_guidance, provenance_guidance):
        assert guidance["disposition"] == "omit"
        assert guidance["suggestions"] == []
        assert guidance["skill_route"] == ["closure-readiness-assessor"]
        require_valid_contract(guidance)


def test_denied_request_does_not_suggest_a_way_around_authority() -> None:
    """Verify denied request does not suggest a way around authority."""
    result = run_planner_request(
        "run serial_ctdna", authority_envelope={"execution": "allowed"}
    )
    guidance = result["next_step_guidance"]

    assert result["status"] == "denied"
    assert guidance["closure_state"] == "blocked"
    assert guidance["disposition"] == "omit"
    assert guidance["suggestions"] == []


def test_localized_refinement_suggests_only_the_minimum_fix_and_rerun() -> None:
    """Verify localized refinement suggests only the minimum fix and rerun."""
    result = {
        "mode": "refine_output_problem",
        "status": "ready_for_semantic_review",
        "planner_receipt": {"digest": "sha256:" + "1" * 64},
        "workflow_refinement_cycle": {
            "fix_plan": {
                "status": "required",
                "diagnostic_target": "normalization-edge",
                "minimal_fix": "Correct the unit mapping on normalization-edge.",
                "targeted_rerun_test_ids": ["test-unit-handoff"],
            }
        },
    }
    guidance = build_next_step_guidance(result)
    suggestion = guidance["suggestions"][0]

    assert guidance["closure_state"] == "repair_required"
    assert suggestion["action"] == "Correct the unit mapping on normalization-edge."
    assert suggestion["target_ids"] == ["normalization-edge", "test-unit-handoff"]
    assert (
        suggestion["authority"]["required"] == "separate_implementation_authorization"
    )
    assert "all targeted rerun tests pass" in suggestion["completion_criterion"]
    require_valid_contract(guidance)


def test_guidance_is_deterministic_and_contains_no_generic_followup() -> None:
    """Verify guidance is deterministic and contains no generic followup."""
    planner_result = {
        "mode": "resume_plan",
        "status": "needs_input",
        "blockers": ["active plan identifier is required"],
        "planner_receipt": {"digest": "sha256:" + "2" * 64},
    }
    first = build_next_step_guidance(planner_result)
    second = build_next_step_guidance(planner_result)

    assert first == second
    rendered = str(first).lower()
    assert "explore further" not in rendered
    assert "anything else" not in rendered
    assert "you could also" not in rendered


def test_route_locked_handoff_continues_in_host_without_duplicate_consent() -> None:
    """Execution approval belongs to execute_plan, not planner suggestions."""

    guidance = build_next_step_guidance(
        {
            "mode": "direct_use",
            "status": "ready_for_semantic_review",
            "planner_receipt": {"digest": "sha256:" + "3" * 64},
            "delivery_handoff": {
                "handoff_id": "handoff-1",
                "route_locked": True,
                "selected_target": {"id": "completed-artifact-packager"},
            },
        }
    )

    assert guidance["closure_state"] == "ready_for_host_continuation"
    assert guidance["disposition"] == "omit"
    assert guidance["suggestions"] == []
    assert "execute_plan" in guidance["reason"]
    require_valid_contract(guidance)
