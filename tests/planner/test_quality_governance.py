# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0

"""Tests for consequence policy, quality elicitation, and lifecycle controls.

This module protects expected behavior for the corresponding workflow, script, or repository surface. Key concepts: regression coverage, interface stability, and output integrity.
"""

from __future__ import annotations

import copy

from lunar_planner import run_planner_request
from lunar_planner.contracts import seal_quality_contract
from lunar_planner.quality_governance import (
    classify_quality_policy,
    criterion_transition_errors,
    material_quality_elicitation,
    normalize_consequence_profile,
    revise_quality_contract,
    update_quality_question_states,
)


def test_consequence_policy_is_paraphrase_invariant_and_not_topic_keyword_based() -> (
    None
):
    """Verify consequence policy is paraphrase invariant and not topic keyword based."""
    consequence = {"multi_stage": True, "handoff_count": 2}
    first = classify_quality_policy(
        {"goal": "Write a melanoma report", "consequence_profile": consequence}
    )
    second = classify_quality_policy(
        {"goal": "Assemble the dossier", "consequence_profile": consequence}
    )
    assert first["tier"] == second["tier"] == "complex"
    assert "composition" in first["evaluator_modes"]

    # A clinical word alone does not manufacture authority; the normalized
    # consequence envelope does.
    assert (
        classify_quality_policy({"goal": "Discuss treatment literature"})["tier"]
        == "ordinary"
    )
    human = classify_quality_policy(
        {
            "goal": "Assess the evidence",
            "consequence_profile": {"clinical_decision": True},
        }
    )
    assert human["tier"] == "human_authority"
    assert human["human_gate"] is True


def test_public_request_consequence_requires_patient_decision_not_a_treatment_topic() -> (
    None
):
    """Verify public request consequence requires patient decision not a treatment topic."""
    decision = normalize_consequence_profile(
        "Use this exploratory signal as proof and make a patient-level treatment decision."
    )
    assert decision["clinical_decision"] is True
    assert decision["human_authority_required"] is True
    discussion = normalize_consequence_profile(
        "Discuss treatment evidence and its limitations for a research audience."
    )
    assert discussion == {}
    assert (
        classify_quality_policy(
            {"goal": "Discuss treatment evidence", "consequence_profile": discussion}
        )["tier"]
        == "ordinary"
    )
    regulatory = normalize_consequence_profile(
        "Submit this dossier to the regulator for marketing authorization."
    )
    assert regulatory["regulatory_decision"] is True
    assert regulatory["human_authority_required"] is True


def test_public_planner_human_authority_request_is_tiered_and_denied() -> None:
    """Verify public planner human authority request is tiered and denied."""
    receipt = run_planner_request(
        "Use this exploratory signal as proof and make a patient-level treatment decision.",
        authority_envelope={"denied_permissions": ["clinical_decision"]},
    )["planner_receipt"]
    assert receipt["outcome_quality_contract"]["risk_tier"] == "human_authority"
    # Consequential requests now stop before catalog selection. The denied
    # authority remains sealed in the request frame and cannot be relaxed by a
    # later quality continuation; delivery policy is created only after the
    # independently reviewed outcome freeze.
    assert receipt["delivery_quality_plan"] is None
    assert receipt["request_frame"]["authority"]["denied_permissions"] == [
        "clinical_decision"
    ]
    assert receipt["preflight"]["authority_status"] == "not_checked"
    assert receipt["disposition"] == "quality_planning_required"


def test_control_and_budget_policy_never_substitute_a_cheaper_pass() -> None:
    """Verify control and budget policy never substitute a cheaper pass."""
    control = classify_quality_policy(
        {"request_class": "capability_help", "control_route": True}
    )
    assert control["tier"] == "control"
    assert control["cost_ceiling_units"] == 0
    assert control["evaluator_modes"] == ["deterministic"]
    ordinary = classify_quality_policy({"goal": "Interpret this bounded finding"})
    assert ordinary["fallback"] == "inconclusive"
    receipt = run_planner_request("List capabilities")["planner_receipt"]
    assert receipt["quality_handoff"]["risk_tier"] == "control"
    assert (
        receipt["quality_handoff"]["independent_quality_validation_required"] is False
    )
    assert receipt["quality_handoff"]["release_authorized"] is True
    assert receipt["quality_handoff"]["semantic_payload_release_authorized"] is False
    assert receipt["quality_disposition"] == "deterministic_control_released"


def test_material_quality_question_is_specific_and_not_repeated() -> None:
    """Verify material quality question is specific and not repeated."""
    frame = {"goal": "Is this report good enough to share?"}
    state = {"active_inputs": {}, "question_history": []}
    question = material_quality_elicitation(frame, state)
    assert question is not None
    assert question["intent"] == "quality:audience_and_intended_use"
    assert "audience" in question["prompt"]
    assert "decision or use" in question["prompt"]

    existing = {
        **question,
        "question_id": "question-1",
        "status": "open",
    }
    repeated = material_quality_elicitation(
        frame, {"active_inputs": {}, "question_history": [existing]}
    )
    assert repeated == {
        "intent": "quality:audience_and_intended_use",
        "status": "already_open",
        "question_id": "question-1",
        "missing_fields": ["audience", "intended_use"],
        "blocking": True,
    }


def test_inferred_tumour_board_audience_needs_no_question_and_convincing_blocks() -> (
    None
):
    """Verify inferred tumour board audience needs no question and convincing blocks."""
    tumour_board = material_quality_elicitation(
        {"goal": "Give our tumour board the finding but do not recommend treatment."},
        {"active_inputs": {}, "question_history": []},
    )
    assert tumour_board is None
    convincing = material_quality_elicitation(
        {"goal": "Make the report more convincing."},
        {"active_inputs": {}, "question_history": []},
    )
    assert convincing is not None
    assert convincing["blocking"] is True
    assert "without strengthening claims" in convincing["prompt"]


def test_public_planner_uses_contextual_quality_question_for_review_examples() -> None:
    """Verify public planner uses contextual quality question for review examples."""
    share = run_planner_request("Is this report good enough to share?")[
        "planner_receipt"
    ]
    assert share["disposition"] == "clarification_required"
    assert [row["intent"] for row in share["elicitation"]["questions"]] == [
        "quality:audience_and_intended_use"
    ]
    tumour_board = run_planner_request(
        "Give our tumour board the finding but do not recommend treatment."
    )["planner_receipt"]
    assert not any(
        str(row.get("intent", "")).startswith("quality:")
        for row in tumour_board["elicitation"]["questions"]
    )
    convincing = run_planner_request("Make the report more convincing.")[
        "planner_receipt"
    ]
    assert [row["intent"] for row in convincing["elicitation"]["questions"]] == [
        "quality:intended_decision_or_weakness"
    ]


def test_public_planner_quality_continuation_does_not_repeat_nonanswer_or_conflict() -> (
    None
):
    """Verify public planner quality continuation does not repeat nonanswer or conflict."""
    first = run_planner_request("Is this report good enough to share?")[
        "planner_receipt"
    ]
    second = run_planner_request(
        "I do not know yet.", continuation=first["continuation"]
    )["planner_receipt"]
    assert second["elicitation"]["questions"] == []
    assert second["elicitation"]["unresolved_question_ids"] == ["question-1"]
    assert second["dialogue_state"]["question_history"][0]["status"] == "non_answer"

    conflict = run_planner_request(
        "Those reader definitions conflict.",
        supplied_inputs={
            "audience": {"_conflict": ["public", "specialist"]},
            "intended_use": "external release",
        },
        continuation=second["continuation"],
    )["planner_receipt"]
    assert conflict["elicitation"]["questions"] == []
    assert conflict["elicitation"]["unresolved_question_ids"] == ["question-1"]
    assert conflict["dialogue_state"]["question_history"][0]["status"] == "conflicting"

    resolved = run_planner_request(
        "Use this for specialist internal review.",
        supplied_inputs={"audience": "specialist", "intended_use": "internal review"},
        continuation=conflict["continuation"],
    )["planner_receipt"]
    assert resolved["dialogue_state"]["question_history"][0]["status"] == "resolved"
    assert not any(
        str(row.get("intent", "")).startswith("quality:")
        for row in resolved["elicitation"]["questions"]
    )


def test_quality_question_records_nonanswer_conflict_and_resolution() -> None:
    """Verify quality question records nonanswer conflict and resolution."""
    question = {
        "question_id": "question-1",
        "intent": "quality:audience_and_intended_use",
        "status": "open",
        "missing_fields": ["audience", "intended_use"],
    }
    nonanswer = update_quality_question_states(
        [question], turn_index=2, supplied_inputs={}, utterance="I do not know yet"
    )
    assert nonanswer[0]["status"] == "non_answer"
    conflict = update_quality_question_states(
        nonanswer,
        turn_index=3,
        supplied_inputs={"audience": {"_conflict": ["public", "specialist"]}},
        utterance="Those audiences conflict",
    )
    assert conflict[0]["status"] == "conflicting"
    resolved = update_quality_question_states(
        conflict,
        turn_index=4,
        supplied_inputs={"audience": "specialist", "intended_use": "internal review"},
        utterance="Use it for specialist internal review",
    )
    assert resolved[0]["status"] == "resolved"


def _contract() -> dict:
    """Contract."""
    return seal_quality_contract(
        {
            "contract_id": "quality-v1",
            "version": 1,
            "lifecycle": "frozen",
            "review_status": "passed",
            "criteria": [
                {
                    "criterion_id": "audience-fit",
                    "lifecycle": "frozen",
                    "severity": "must_pass",
                    "separation_required": True,
                    "evaluator_mode": "generative",
                    "pass_condition": "specialist terminology is bounded",
                    "authority_ceiling": "research only",
                    "prohibited_outcomes": ["treatment recommendation"],
                    "invalidation_inputs": ["consumer", "audience"],
                },
                {
                    "criterion_id": "route-binding",
                    "lifecycle": "frozen",
                    "severity": "must_pass",
                    "separation_required": False,
                    "evaluator_mode": "deterministic",
                    "pass_condition": "binding matches",
                    "authority_ceiling": "route only",
                    "prohibited_outcomes": ["route substitution"],
                    "invalidation_inputs": ["selected route", "bindings"],
                },
                {
                    "criterion_id": "evidence-boundary",
                    "lifecycle": "frozen",
                    "severity": "must_pass",
                    "separation_required": True,
                    "evaluator_mode": "hybrid",
                    "pass_condition": "claims use the whitelist",
                    "authority_ceiling": "claim ceiling",
                    "prohibited_outcomes": ["invent evidence"],
                    "invalidation_inputs": ["evidence whitelist", "claim ceiling"],
                },
            ],
        }
    )


def test_dependency_changes_selectively_invalidate_and_forbid_assessment_reuse() -> (
    None
):
    """Verify dependency changes selectively invalidate and forbid assessment reuse."""
    contract = _contract()
    for dependency, expected in (
        ("audience", ["audience-fit"]),
        ("selected route", ["route-binding"]),
        ("bindings", ["route-binding"]),
        ("evidence whitelist", ["evidence-boundary"]),
        ("claim ceiling", ["evidence-boundary"]),
    ):
        result = revise_quality_contract(
            contract,
            [
                {
                    "dependency": dependency,
                    "old_digest": "old",
                    "new_digest": "new",
                    "source_turn_id": "turn-2",
                }
            ],
            next_version=2,
            actor_kind="user",
            parent_digest=contract["digest"],
        )
        assert result["status"] == "revised"
        assert result["invalidated_criterion_ids"] == expected
        assert result["assessment_reuse_allowed"] is False


def test_noop_stale_tampered_and_mandatory_withdrawal_fail_closed() -> None:
    """Verify noop stale tampered and mandatory withdrawal fail closed."""
    contract = _contract()
    no_op = revise_quality_contract(
        contract,
        [{"dependency": "audience", "old_digest": "same", "new_digest": "same"}],
        next_version=2,
        actor_kind="user",
        parent_digest=contract["digest"],
    )
    assert no_op["status"] == "no_op"
    assert (
        revise_quality_contract(
            contract,
            [],
            next_version=2,
            actor_kind="user",
            parent_digest="sha256:" + "0" * 64,
        )["reason"]
        == "stale_or_tampered_parent"
    )
    tampered = copy.deepcopy(contract)
    tampered["criteria"][0]["pass_condition"] = "weaker"
    assert (
        revise_quality_contract(
            tampered,
            [],
            next_version=2,
            actor_kind="user",
            parent_digest=contract["digest"],
        )["reason"]
        == "stale_or_tampered_parent"
    )

    withdrawal = revise_quality_contract(
        contract,
        [
            {
                "dependency": "claim ceiling",
                "action": "withdraw",
                "criterion_id": "evidence-boundary",
                "old_digest": "old",
                "new_digest": "withdrawn",
            }
        ],
        next_version=2,
        actor_kind="user",
        parent_digest=contract["digest"],
    )
    assert withdrawal["status"] == "rejected"


def test_failed_assessment_and_planner_inference_cannot_weaken_must_pass() -> None:
    """Verify failed assessment and planner inference cannot weaken must pass."""
    previous = _contract()["criteria"][0]
    weaker = {
        **previous,
        "severity": "should_pass",
        "separation_required": False,
        "prohibited_outcomes": [],
    }
    errors = criterion_transition_errors(
        previous, weaker, actor_kind="planner", trigger="failed_assessment"
    )
    assert "planner or evaluator cannot downgrade a must-pass criterion" in errors
    assert "planner or evaluator cannot remove producer/evaluator separation" in errors
    assert "a failed assessment cannot relax or rewrite its criterion" in errors
