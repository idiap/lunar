# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0

"""Five-turn and state-transition conformance for the public planner.

This module protects expected behavior for the corresponding workflow, script, or repository surface. Key concepts: regression coverage, interface stability, and output integrity.
"""

from __future__ import annotations

import copy

from lunar_planner.contracts import (
    seal_quality_contract,
)
from lunar_planner.staged_routing import (
    freeze_quality_plan,
    review_quality_plan,
)

from lunar_planner import (
    normalize_request,
    plan_capability_gaps,
    run_planner_request,
    run_planner_request_with_test_surface,
    validate_contract,
)
from tests.planner.quality_test_support import authorize_test_plan_review


def _routed_turn(
    command: str,
    *,
    surface: dict | None = None,
    **kwargs,
) -> dict:
    """Routed turn."""
    runner = (
        run_planner_request
        if surface is None
        else run_planner_request_with_test_surface
    )
    call = (
        (lambda text, **values: runner(text, **values))
        if surface is None
        else (lambda text, **values: runner(text, surface, **values))
    )
    first = call(command, **kwargs)["planner_receipt"]
    assert first["disposition"] == "quality_planning_required", first["disposition"]
    outcome = copy.deepcopy(first["outcome_quality_contract"])
    for criterion in outcome["criteria"]:
        criterion["observable"] = (
            "The planned artifact visibly covers every named operation, entity, "
            f"qualifier, and evidence boundary in this obligation: {first['request_frame']['goal']}"
        )
        criterion["required_anchors"] = [
            "active requirement",
            "candidate artifact",
            "evidence boundary",
        ]
    outcome = seal_quality_contract(outcome)
    review = review_quality_plan(
        outcome, reviewer={"id": "dialogue-test-quality-critic"}, independent=True
    )
    assert review["verdict"] == "pass", review
    frozen = freeze_quality_plan(outcome, review)
    authorized_review = authorize_test_plan_review(
        outcome, review, "dialogue-test-criterion-producer"
    )
    return call(
        "Resume after independent outcome-quality review.",
        continuation=first["continuation"],
        supplied_inputs={
            "frozen_outcome_quality_contract": frozen,
            "outcome_quality_review": review,
            "authorized_outcome_quality_review": authorized_review,
        },
    )["planner_receipt"]


def _skill(
    name: str,
    description: str,
    *,
    input_type: str | None = None,
    output_type: str | None = None,
) -> dict:
    """Skill."""
    inputs = (
        []
        if input_type is None
        else [{"name": "source", "type": input_type, "required": True}]
    )
    outputs = [] if output_type is None else [{"name": "result", "type": output_type}]
    return {
        "id": name,
        "name": name,
        "scope": "package",
        "description": description,
        "purpose": description,
        "triggers": description,
        "non_triggers": "",
        "source_path": f"catalog/{name}/SKILL.md",
        "available": True,
        "invocation_posture": "instruction_only",
        "content_digest": "sha256:" + "0" * 64,
        "aliases": [],
        "interface": {
            "inputs": {"status": "documented", "items": inputs},
            "outputs": {"status": "documented", "items": outputs},
        },
        "authority": {},
    }


def _surface(*skills: dict) -> dict:
    """Surface."""
    return {
        "schema_version": "lunar.planner.surface-index/v1",
        "skills": list(skills),
        "workflow_packages": [],
        "subworkflows": [],
    }


def _collection_surface():
    skill = _skill(
        "collection-builder",
        "Create and validate an isolated evidence collection",
        output_type="collection",
    )
    skill["interface"]["inputs"]["items"] = [
        {"name": name, "type": "object", "required": True}
        for name in ("identity", "profile", "policy")
    ]
    skill["authority"] = {"permissions": ["write_files"]}
    return _surface(skill)


def test_ready_route_emits_refinable_caller_held_state() -> None:
    """Verify ready route emits refinable caller held state."""
    receipt = _routed_turn("Turn this checked formal claim into a bounded explanation")
    assert receipt["disposition"] == "delivery_quality_planning_required"
    assert receipt["continuation"] is not None
    assert receipt["dialogue_state"]["turn_index"] == 1

    second = run_planner_request(
        "Keep the assumptions explicit for a non-specialist reader",
        continuation=receipt["continuation"],
    )["planner_receipt"]
    assert second["dialogue_state"]["turn_index"] == 2
    assert (
        second["dialogue_state"]["parent_stage_digest"]
        == receipt["dialogue_state"]["current_stage_digest"]
    )


def test_prior_typed_inputs_are_carried_and_replaced_without_resending() -> None:
    """Verify prior typed inputs are carried and replaced without resending."""
    first = _routed_turn(
        "Create and validate an isolated evidence collection",
        surface=_collection_surface(),
        supplied_inputs={
            "identity": {"name": "trial-evidence"},
            "profile": {"type": "clinical-review"},
        },
    )
    second = _routed_turn(
        "Use a deny-network policy",
        surface=_collection_surface(),
        continuation=first["continuation"],
    )
    assert second["binding"]["status"] == "complete"
    assert set(second["dialogue_state"]["active_inputs"]) == {
        "identity",
        "profile",
        "policy",
    }
    assert second["dialogue_state"]["active_inputs"]["policy"] == {
        "text": "Use a deny-network policy"
    }

    third = run_planner_request_with_test_surface(
        "Actually use the clinical-evidence profile instead of the clinical-review profile",
        _collection_surface(),
        supplied_inputs={"profile": {"type": "clinical-evidence"}},
        continuation=second["continuation"],
    )["planner_receipt"]
    profiles = [
        row for row in third["dialogue_state"]["facts"] if row["name"] == "profile"
    ]
    assert [row["status"] for row in profiles] == ["superseded", "active"]
    assert third["dialogue_state"]["active_inputs"]["profile"] == {
        "type": "clinical-evidence"
    }


def test_one_off_correction_retracts_stale_change_intent() -> None:
    """Verify one off correction retracts stale change intent."""
    first = run_planner_request(
        "Design a reusable workflow for checked-claim explanation"
    )["planner_receipt"]
    assert first["request_frame"]["persistent_change_requested"] is True
    assert first["dialogue_state"]["planning_phase"] == "framing"

    second = run_planner_request(
        "Actually this is a one-off analysis, not a reusable workflow",
        continuation=first["continuation"],
    )["planner_receipt"]
    assert second["request_frame"]["persistent_change_requested"] is False
    assert any(
        row["status"] == "superseded" for row in second["dialogue_state"]["turns"][:-1]
    )


def test_one_off_correction_replaces_obligation_in_contract_tests() -> None:
    """Verify one off correction replaces obligation in contract tests."""
    first = run_planner_request(
        "Design a reusable workflow for checked-claim explanation"
    )["planner_receipt"]
    second = run_planner_request(
        "To clarify, this is a one-off analysis rather than a reusable workflow",
        continuation=first["continuation"],
    )["planner_receipt"]
    requirement = second["requirement_ledger"]["requirements"][0]
    assert requirement["revision"] == "replaced_scope"
    assert requirement["active_text"].startswith("To clarify")
    assert all(
        "Design a reusable workflow" not in criterion
        for criterion in requirement["correctness_criteria"]
    )


def test_authoritative_terminal_artifact_persists_through_finalization() -> None:
    """Verify authoritative terminal artifact persists through finalization."""
    surface = _surface(
        _skill(
            "evidence-memo-writer",
            "Write evidence into a bounded decision memo",
            output_type="evidence_memo",
        )
    )
    first = run_planner_request_with_test_surface(
        "Build a workflow that writes the evidence summary",
        surface,
        supplied_inputs={"terminal_artifact": "two-page decision memo"},
    )["planner_receipt"]
    final = _routed_turn(
        "Finalize and return the instantiated workflow",
        surface=surface,
        continuation=first["continuation"],
    )
    assert final["workflow_draft"]["terminal_artifact"] == "two-page decision memo"
    assert (
        final["workflow_instantiation"]["terminal_artifact"] == "two-page decision memo"
    )
    assert (
        final["workflow_instantiation"]["nodes"][-1]["output_type"]
        == "two-page decision memo"
    )


def test_implicit_multiturn_requirements_form_a_typed_draft() -> None:
    """Verify implicit multiturn requirements form a typed draft."""
    surface = _surface(
        _skill(
            "cohort-record-normalizer",
            "Normalize cohort records into a harmonized record",
            output_type="normalized_record",
        ),
        _skill(
            "cohort-record-summarizer",
            "Summarize normalized cohort records into a bounded report",
            input_type="normalized_record",
            output_type="summary_report",
        ),
    )
    first = run_planner_request_with_test_surface(
        "Build a small reusable workflow to normalize cohort records",
        surface,
    )["planner_receipt"]
    second = _routed_turn(
        "I also need to summarize the normalized records into a bounded report",
        surface=surface,
        supplied_inputs={"source": {"fixture": "normalized-records"}},
        continuation=first["continuation"],
    )
    draft = second["workflow_draft"]
    assert len(second["requirement_ledger"]["requirements"]) == 2
    assert {node["component"]["id"] for node in draft["nodes"]} == {
        "cohort-record-normalizer",
        "cohort-record-summarizer",
    }
    assert draft["edges"] == [
        {
            "edge_id": "edge-1",
            "from_node": "node-1",
            "to_node": "node-2",
            "artifact_type": "normalized_record",
            "required_input_types": ["normalized_record"],
            "compatibility": "documented_compatible",
            "invented_mapping": False,
        }
    ]
    instantiation = second["workflow_instantiation"]
    assert instantiation["requirement_coverage_complete"] is True
    assert [node["implementation_kind"] for node in instantiation["nodes"]] == [
        "existing_component",
        "existing_component",
    ]


def test_open_question_is_not_repeated_and_never_exposes_internal_alternatives() -> (
    None
):
    """Verify open question is not repeated and never exposes internal alternatives."""
    surface = _surface(
        _skill(
            "molecular-assessor-a",
            "Assess molecular evidence and return a bounded finding",
        ),
        _skill(
            "molecular-assessor-b",
            "Assess molecular evidence and return a bounded finding",
        ),
    )
    first = _routed_turn(
        "Assess this molecular evidence and return a bounded finding",
        surface=surface,
    )
    assert len(first["elicitation"]["questions"]) == 1
    prompt = first["elicitation"]["questions"][0]["prompt"]
    assert "molecular-assessor" not in prompt

    second = run_planner_request_with_test_surface(
        "The same evidence packet is still being assembled",
        surface,
        continuation=first["continuation"],
    )["planner_receipt"]
    assert second["elicitation"]["questions"] == []
    assert second["elicitation"]["unresolved_question_ids"] == ["question-1"]
    assert second["elicitation"]["repeated_question"] is False


def test_stable_ambiguous_responsibility_becomes_a_governed_gap() -> None:
    """Verify stable ambiguous responsibility becomes a governed gap."""
    surface = _surface(
        _skill(
            "molecular-assessor-a",
            "Assess molecular evidence and return a bounded finding",
        ),
        _skill(
            "molecular-assessor-b",
            "Assess molecular evidence and return a bounded finding",
        ),
    )
    receipt = _routed_turn(
        "Build a reusable workflow to assess molecular evidence and return a bounded finding",
        surface=surface,
    )
    unresolved = [
        node
        for node in receipt["workflow_instantiation"]["nodes"]
        if node["implementation_kind"].startswith("proposed_")
    ]
    assert unresolved
    assert receipt["proposed_skill_test_plans"]


def test_capability_gap_is_content_specified_and_can_be_retracted_by_reuse() -> None:
    """Verify capability gap is content specified and can be retracted by reuse."""
    requirement = {
        "requirement_id": "requirement-1",
        "text": "Build a reusable spectral vortex record normalizer",
        "active_text": "Build a reusable spectral vortex record normalizer",
        "desired_output": "normalized spectral vortex records",
        "correctness_criteria": ["preserve record identity and provenance"],
        "stability": "stable",
    }
    frame = normalize_request(requirement["text"])
    first = plan_capability_gaps(frame, _surface(), requirement_rows=[requirement])
    assert (
        first["gaps"][0]["proposed_interface"]["correctness_criteria"]
        == requirement["correctness_criteria"]
    )
    assert first["gaps"][0]["creation_authorized"] is False

    second = plan_capability_gaps(
        frame,
        _surface(
            _skill(
                "spectral-vortex-record-normalizer",
                "Normalize spectral vortex records while preserving identity and provenance",
            )
        ),
        requirement_rows=[requirement],
        prior_plan=first,
    )
    assert second["status"] == "reuse_complete"
    assert second["retracted_gaps"][0]["status"] == "retracted"
    assert (
        second["retracted_gaps"][0]["replacement_component"]["id"]
        == "spectral-vortex-record-normalizer"
    )


def test_dialogue_state_and_workflow_draft_validate_against_public_schemas() -> None:
    """Verify dialogue state and workflow draft validate against public schemas."""
    receipt = run_planner_request(
        "Turn this checked formal claim into a bounded explanation"
    )["planner_receipt"]
    assert validate_contract(receipt["dialogue_state"]).valid
    assert validate_contract(receipt["requirement_ledger"]).valid
    assert validate_contract(receipt["workflow_draft"]).valid
    assert receipt["workflow_instantiation"] is None


def test_final_instantiation_covers_gap_and_builds_new_skill_test_specifications() -> (
    None
):
    """Verify final instantiation covers gap and builds new skill test specifications."""
    receipt = _routed_turn(
        "Produce a reusable workflow that imports records from an external spectral vortex GraphQL service",
        surface=_surface(),
    )
    instantiation = receipt["workflow_instantiation"]
    assert instantiation["requirement_coverage_complete"] is True
    assert instantiation["status"] == "instantiated_with_blockers"
    assert len(instantiation["nodes"]) == 1
    node = instantiation["nodes"][0]
    assert node["implementation_kind"] == "proposed_adapter"
    assert node["status"] == "proposed_unavailable"
    assert node["creation_authorized"] is False
    assert instantiation["proposed_skill_test_plan_ids"] == [node["test_plan_id"]]

    test_plan = receipt["proposed_skill_test_plans"][0]
    assert validate_contract(receipt["dialogue_state"]).valid
    assert validate_contract(test_plan).valid
    assert test_plan["implementation_authorized"] is False
    assert test_plan["test_files_written"] is False
    assert {row["test_id"].rsplit("-", 1)[-1] for row in test_plan["test_cases"]} >= {
        "contract",
        "input",
        "conflict",
        "boundary",
        "offline",
    }
    cycle = receipt["workflow_refinement_cycle"]
    assert validate_contract(cycle).valid
    assert cycle["status"] == "blocked_for_refinement"
    assert cycle["release_gate"] == "blocked_pending_execution_validation"
    assert {row["owner"] for row in cycle["findings"]} == {"instantiated-1"}


def test_refinement_cycle_requires_content_addressed_execution_evidence() -> None:
    """Verify refinement cycle requires content addressed execution evidence."""
    surface = _surface(
        _skill(
            "cohort-record-normalizer",
            "Normalize cohort records into a harmonized record",
            output_type="normalized_record",
        )
    )
    first = _routed_turn(
        "Produce a reusable workflow to normalize cohort records",
        surface=surface,
    )
    verification = first["post_plan_evidence_verification"]
    assert verification["base_plan_digest"] == first["workflow_instantiation"]["digest"]
    assert verification["base_plan_digest_preserved"] is True
    assert verification["base_plan_mutation_performed"] is False
    assert validate_contract(verification).valid
    cycle = first["workflow_refinement_cycle"]
    assert cycle["status"] == "ready_for_controlled_execution"
    assert cycle["pre_execution_ready"] is True
    assert cycle["execution_validated"] is False
    assert cycle["release_gate"] == "blocked_pending_execution_validation"
    assert any(
        row["kind"].startswith("post_plan_verification:")
        for row in cycle["workflow_test_specifications"]
    )

    results = {
        "test_results": [
            {
                "test_id": test_id,
                "status": "passed",
                "evidence_digest": "sha256:" + "a" * 64,
            }
            for test_id in cycle["required_test_ids"]
        ]
    }
    second = _routed_turn(
        "The controlled execution and terminal checks completed",
        surface=surface,
        supplied_inputs={"workflow_execution_results": results},
        continuation=first["continuation"],
    )
    refined = second["workflow_refinement_cycle"]
    assert refined["iteration"] == 2
    assert refined["status"] == "validated_for_release"
    assert refined["execution_validated"] is True
    assert refined["release_gate"] == "passed"
    assert refined["missing_execution_test_ids"] == []


def test_refinement_cycle_targets_failure_without_discarding_verified_tests() -> None:
    """Verify refinement cycle targets failure without discarding verified tests."""
    surface = _surface(
        _skill(
            "cohort-record-normalizer",
            "Normalize cohort records",
            output_type="normalized_record",
        )
    )
    first = _routed_turn(
        "Produce a reusable workflow to normalize cohort records",
        surface=surface,
    )
    required = first["workflow_refinement_cycle"]["required_test_ids"]
    results = {
        "test_results": [
            {
                "test_id": test_id,
                "status": "failed" if index == len(required) - 1 else "passed",
                "evidence_digest": "sha256:" + str(index + 1).zfill(64),
            }
            for index, test_id in enumerate(required)
        ]
    }
    second = _routed_turn(
        "One controlled execution check failed; retain the passing evidence",
        surface=surface,
        supplied_inputs={"workflow_execution_results": results},
        continuation=first["continuation"],
    )
    cycle = second["workflow_refinement_cycle"]
    assert cycle["status"] == "blocked_for_refinement"
    assert cycle["diagnostic"]["localized_target"] == "workflow"
    assert cycle["diagnostic"]["layer"] == "terminal_artifact"
    assert cycle["fix_plan"]["broad_rebuild_allowed"] is False
    assert cycle["fix_plan"]["invalidate_test_ids"] == [required[-1]]
    assert set(cycle["fix_plan"]["preserve_test_ids"]) == set(required[:-1])
    assert cycle["fix_plan"]["targeted_rerun_test_ids"] == [required[-1]]

    rerun = {
        "test_results": [
            {
                "test_id": required[-1],
                "status": "passed",
                "evidence_digest": "sha256:" + "f" * 64,
            }
        ]
    }
    third = _routed_turn(
        "The repaired terminal artifact now passes its targeted rerun",
        surface=surface,
        supplied_inputs={"workflow_execution_results": rerun},
        continuation=second["continuation"],
    )
    final_cycle = third["workflow_refinement_cycle"]
    assert final_cycle["iteration"] == 3
    assert final_cycle["status"] == "validated_for_release"
    assert set(final_cycle["verified_test_ids"]) == set(required)


def test_five_turn_state_retains_correction_and_never_invents_authority() -> None:
    """Verify five turn state retains correction and never invents authority."""
    turns = [
        (
            "I want a small reusable workflow to compare suppressive myeloid states across two tumour atlases",
            {},
        ),
        (
            "The studies have count matrices and donor metadata",
            {"data_modality": "bulk RNA-seq"},
        ),
        (
            "Actually these are single-cell matrices, not bulk RNA-seq",
            {"data_modality": "single-cell RNA-seq"},
        ),
        (
            "Raw matrices cannot leave our environment; include batch-aware validation",
            {"network_policy": "deny"},
        ),
        ("Produce the compact workflow and expose unresolved adapter needs", {}),
    ]
    continuation = None
    receipt = None
    for text, inputs in turns:
        receipt = run_planner_request(
            text, supplied_inputs=inputs, continuation=continuation
        )["planner_receipt"]
        continuation = receipt["continuation"]
    assert receipt is not None
    state = receipt["dialogue_state"]
    assert state["turn_index"] == 5
    assert state["active_inputs"]["data_modality"] == "single-cell RNA-seq"
    assert state["active_inputs"]["network_policy"] == "deny"
    assert state["authority"] == {}
    assert len(state["turns"]) == 5
    assert all(
        row["creation_authorized"] is False
        for row in (receipt["capability_gap_plan"] or {}).get("gaps", ())
    )


def test_withdrawn_requirement_and_conflicting_fact_remain_auditable() -> None:
    """Verify withdrawn requirement and conflicting fact remain auditable."""
    first = run_planner_request(
        "Build a reusable workflow to explain a checked claim and then write a bounded summary",
        supplied_inputs={"audience": "specialist"},
    )["planner_receipt"]
    second = run_planner_request(
        "We no longer need the bounded summary",
        supplied_inputs={"audience": {"_conflict": ["specialist", "public"]}},
        continuation=first["continuation"],
    )["planner_receipt"]
    requirements = second["requirement_ledger"]["requirements"]
    assert requirements[1]["status"] == "withdrawn"
    audience = [
        row for row in second["dialogue_state"]["facts"] if row["name"] == "audience"
    ]
    assert audience[-1]["relation"] == "contradict"
    assert audience[0]["status"] == "superseded"


def test_late_authority_denial_repreflights_existing_workflow_nodes() -> None:
    """Verify late authority denial repreflights existing workflow nodes."""
    first = run_planner_request_with_test_surface(
        "Create an isolated evidence collection from this identity, profile and policy, then validate it",
        _collection_surface(),
        supplied_inputs={"identity": {}, "profile": {}, "policy": {}},
    )["planner_receipt"]
    second = _routed_turn(
        "Keep the same scientific outcome, but file writing is not authorized",
        surface=_collection_surface(),
        authority_envelope={"denied_permissions": ["write_files"]},
        continuation=first["continuation"],
    )
    assert second["dialogue_state"]["authority"]["denied_permissions"] == [
        "write_files"
    ]
    assert any(
        node["preflight"]["authority_status"] == "denied"
        for node in second["workflow_draft"]["nodes"]
    )
