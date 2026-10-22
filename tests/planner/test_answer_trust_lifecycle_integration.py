# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0

"""Tests for Answer trust lifecycle integration.

This module protects expected behavior for the corresponding workflow, script, or repository surface. Key concepts: regression coverage, interface stability, and output integrity.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from lunar_planner.answer_trust import (
    DEFAULT_POLICY,
    assess_answer_trust,
    build_answer_control_readiness,
    build_readiness_card,
    resolve_answer_trust_rollout,
)
import lunar_planner.quality_authorization as quality_authorization
from lunar_planner.answer_trust_calibration import calibrate_answer_trust
from lunar_planner.contracts import (
    canonical_digest,
    load_profile,
    seal_quality_contract,
    validate_contract,
    validate_profile,
)
from lunar_planner.post_plan_verification import build_post_plan_verification
from lunar_planner.quality_authorization import (
    _seal_signed,
    assess_authorized_answer_trust,
    issue_answer_trust_authorization,
    persist_authorized_answer_trust,
)
from lunar_planner.staged_routing import (
    build_workflow_refinement_cycle,
    plan_stages,
)

ROOT = Path(__file__).resolve().parents[2]
RESOURCES = ROOT / "app/backend/lunar_planner/resources"
KEY = b"answer-trust-lifecycle-test-key-000000000000000"


def _sealed_plan_and_ledger() -> tuple[dict, dict]:
    """Sealed plan and ledger."""
    plan = {
        "schema_version": "lunar.planner.workflow-instantiation/v1",
        "dialogue_id": "trust-lifecycle",
        "turn_index": 1,
        "status": "instantiated_ready",
        "requirement_coverage_complete": True,
        "nodes": [
            {
                "node_id": "node-1",
                "requirement_id": "req-1",
                "requirement_ids": ["req-1"],
                "implementation_kind": "existing_component",
                "component": {"id": "bounded-scientific-writer"},
                "status": "ready",
                "inputs": [],
                "output_type": "bounded statement",
                "correctness_criteria": ["The exact value remains source linked"],
                "creation_authorized": False,
            }
        ],
        "edges": [],
        "terminal_artifact": "bounded statement",
        "blockers": [],
        "mapping_review_edge_ids": [],
        "proposed_skill_test_plan_ids": [],
        "route_only": True,
        "execution_authorized": False,
        "structure_digest": "sha256:" + "a" * 64,
    }
    plan["digest"] = canonical_digest(plan)
    ledger = {
        "requirements": [
            {
                "requirement_id": "req-1",
                "status": "active",
                "active_text": "The source field contains 37 participants",
                "desired_output": "bounded statement",
                "consumer": "researcher",
                "source_turn_index": 1,
                "correctness_criteria": ["Preserve the exact value and locator"],
            }
        ],
        "digest": "sha256:" + "b" * 64,
    }
    return plan, ledger


def _authorized_quality(answer: dict) -> dict:
    """Authorized quality."""
    quality = seal_quality_contract(
        {
            "schema_version": "lunar.planner.quality-assessment/v1",
            "assessment_id": "quality-answer-trust",
            "root_interaction_id": "interaction-answer-trust",
            "operation_role": "artifact_assessment",
            "parent_digest": "sha256:" + "1" * 64,
            "principal": {"id": "test-user", "kind": "user"},
            "canonical_serialization": "canonical-json-v1",
            "evidence_manifest_digest": "sha256:" + "2" * 64,
            "quality_plan_digest": "sha256:" + "3" * 64,
            "artifact_digest": canonical_digest(answer),
            "evaluator": {"id": "independent-quality-reviewer"},
            "independent": True,
            "criterion_results": [
                {
                    "criterion_id": "answer-fidelity",
                    "severity": "must_pass",
                    "evaluator_mode": "deterministic",
                    "verdict": "pass",
                    "artifact_anchors": ["answer:claim-1"],
                    "source_anchors": ["table-1/row-2/value"],
                    "contradictions": [],
                    "unsupported_claims": [],
                    "uncertainty": "bounded",
                }
            ],
            "verdict": "pass",
            "presentable_as_user_answer": False,
        }
    )
    assert validate_contract(quality).valid, validate_contract(quality).errors
    return _seal_signed(
        {
            "schema_version": "lunar.planner.authorized-quality-assessment/v1",
            "assessment": quality,
            "authorization_digest": "sha256:" + "4" * 64,
            "result_attestation_digest": "sha256:" + "5" * 64,
            "anchor_manifest_digest": "sha256:" + "6" * 64,
            "deterministic_receipt_digests": [],
        },
        KEY,
    )


def test_readiness_profile_and_default_off_runtime_contract() -> None:
    """Verify readiness profile and default off runtime contract."""
    profile_path = RESOURCES / "profiles/answer-control-readiness.yaml"
    profile = load_profile(profile_path, repo_root=ROOT)
    report = validate_profile(profile, repo_root=ROOT)
    assert report.valid, report.errors
    assert profile["status"] == "planning_only_non_executing"
    assert profile["stages"][0]["outputs"] == ["answer_control_readiness"]

    manifest = json.loads((RESOURCES / "planner-manifest.json").read_text())
    assert manifest["answer_trust"]["default_enabled"] is False
    assert (
        inspect.signature(plan_stages)
        .parameters["answer_trust_readiness_enabled"]
        .default
        is False
    )
    assert (
        inspect.signature(plan_stages).parameters["answer_trust_rollout_state"].default
        == "off"
    )
    assert resolve_answer_trust_rollout("shadow")["release_effect_enabled"] is False
    blocked_promotion = resolve_answer_trust_rollout("enforcement")
    assert blocked_promotion["effective_state"] == "advisory"
    assert blocked_promotion["promotion_blockers"]


def test_readiness_adds_score_free_receipt_obligations_to_refinement() -> None:
    """Verify readiness adds score free receipt obligations to refinement."""
    plan, ledger = _sealed_plan_and_ledger()
    verification = build_post_plan_verification(plan, ledger)
    readiness = build_answer_control_readiness(plan, verification)

    assert validate_contract(readiness).valid, validate_contract(readiness).errors
    assert readiness["realized_trust_score"] is None
    assert "score" not in readiness
    assert readiness["mutates_initial_plan"] is False
    card = build_readiness_card(readiness)
    assert card["realized_trust_score"] is None
    assert "Prospective control readiness" in card["interpretation"]

    cycle = build_workflow_refinement_cycle(
        {
            "active_inputs": {},
            "dialogue_id": "trust-lifecycle",
            "planning_phase": "ready_for_review",
        },
        plan,
        [],
        post_plan_verification=verification,
        answer_control_readiness=readiness,
    )
    trust_tests = [
        row
        for row in cycle["workflow_test_specifications"]
        if row["kind"] == "answer_control_readiness:observed_receipt"
    ]
    assert trust_tests
    assert all(
        "observed receipt" in row["required_assertions"][0] for row in trust_tests
    )


def test_authorized_realized_assessment_binds_inputs_and_persists_explicitly() -> None:
    """Verify authorized realized assessment binds inputs and persists explicitly."""
    answer = {
        "execution_state": "observed",
        "base_plan_digest": "sha256:" + "a" * 64,
        "evidence_manifest_digest": "sha256:" + "b" * 64,
        "components": [{"component_id": "answer:claim-1"}],
        "text": "The source reports 37 participants.",
    }
    answer["digest"] = canonical_digest(answer)
    claims = [
        {
            "claim_id": "claim-1",
            "claim_class": "material_factual",
            "component_ids": ["answer:claim-1"],
            "evidence_ids": ["evidence-1"],
            "release_critical": True,
        }
    ]
    evidence = [
        {
            "evidence_id": "evidence-1",
            "origin": "external",
            "authorized": True,
            "observed_consumed": True,
            "content_digest": "sha256:" + "c" * 64,
            "locator": "table-1/row-2/value",
            "independence_cluster": "study-1",
            "authority_fit": 1.0,
            "directness": 1.0,
            "applicability": 1.0,
        }
    ]
    edges = [
        {
            "edge_id": "edge-1",
            "input_ids": ["evidence-1"],
            "output_id": "claim-1",
            "kind": "exact",
            "observed": True,
        }
    ]
    provenance = {
        "summary": {
            "release_blocking": False,
            "complete": True,
            "component_count": 1,
            "status_counts": {"matched": 1},
        },
    }
    authorized_quality = _authorized_quality(answer)
    authorization = issue_answer_trust_authorization(
        answer,
        claims,
        evidence,
        edges,
        authorized_quality_assessment=authorized_quality,
        provenance_reconciliation=provenance,
        policy_digest=DEFAULT_POLICY["policy_digest"],
        nonce="trust-lifecycle",
        trusted_key=KEY,
    )
    package = assess_authorized_answer_trust(
        answer,
        claims,
        evidence,
        edges,
        authorization=authorization,
        authorized_quality_assessment=authorized_quality,
        provenance_reconciliation=provenance,
        trusted_key=KEY,
    )
    assessment = package["assessment"]
    assert validate_contract(assessment).valid, validate_contract(assessment).errors
    assert assessment["answer_digest"] == answer["digest"]
    assert assessment["polarity"] == "observed_only"
    with pytest.raises(ValueError, match="inputs changed"):
        assess_authorized_answer_trust(
            answer,
            claims,
            [{**evidence[0], "locator": "different/value"}],
            edges,
            authorization=authorization,
            authorized_quality_assessment=authorized_quality,
            provenance_reconciliation=provenance,
            trusted_key=KEY,
        )

    class MemoryStore:
        """Represent memory store."""

        def __init__(self) -> None:
            """Initialize memory store."""
            self.writes: list[tuple[str, bytes]] = []

        def read(self, logical_id: str) -> bytes:
            """Read."""
            raise KeyError(logical_id)

        def write(self, logical_id: str, payload: bytes) -> dict:
            """Write."""
            self.writes.append((logical_id, payload))
            return {"logical_id": logical_id, "size": len(payload)}

    store = MemoryStore()
    receipt = persist_authorized_answer_trust(
        package,
        plan_id="trust-lifecycle",
        artifact_store=store,
        trusted_key=KEY,
    )
    assert receipt["logical_id"].startswith(
        "artifacts/runs/planner/trust-lifecycle/answer-trust-assessment-"
    )
    assert json.loads(store.writes[0][1])["digest"] == package["digest"]


def test_opt_in_trust_gate_can_only_narrow_final_delivery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify opt in trust gate can only narrow final delivery."""
    answer = {
        "execution_state": "observed",
        "components": [{"component_id": "answer:claim-1"}],
        "text": "A remembered value is presented as a result.",
    }
    answer["digest"] = canonical_digest(answer)
    trust = assess_answer_trust(
        answer,
        [
            {
                "claim_id": "claim-1",
                "claim_class": "material_factual",
                "component_ids": ["answer:claim-1"],
                "evidence_ids": ["memory-1"],
                "release_critical": True,
            }
        ],
        [
            {
                "evidence_id": "memory-1",
                "origin": "model_memory",
                "authorized": False,
                "observed_consumed": True,
                "content_digest": None,
                "locator": None,
                "independence_cluster": "generated",
            }
        ],
        [
            {
                "edge_id": "edge-memory",
                "input_ids": ["memory-1"],
                "output_id": "claim-1",
                "kind": "semantic",
                "observed": True,
            }
        ],
    )
    assert trust["status"] == "blocked"
    trust_package = _seal_signed(
        {
            "schema_version": "lunar.planner.authorized-answer-trust-assessment/v1",
            "authorization_digest": "sha256:" + "7" * 64,
            "assessment": trust,
        },
        KEY,
    )
    authorized_quality = _authorized_quality(answer)

    def released(*_args: object, **_kwargs: object) -> dict:
        """Released."""
        return seal_quality_contract(
            {
                "schema_version": "lunar.planner.final-delivery-decision/v1",
                "decision_id": "decision-trust-gate",
                "root_interaction_id": "interaction-answer-trust",
                "operation_role": "final_delivery",
                "parent_digest": "sha256:" + "1" * 64,
                "principal": {"id": "test-user", "kind": "user"},
                "canonical_serialization": "canonical-json-v1",
                "evidence_manifest_digest": "sha256:" + "2" * 64,
                "quality_plan_digest": "sha256:" + "3" * 64,
                "assessment_digest": authorized_quality["assessment"]["digest"],
                "artifact_digest": canonical_digest(answer),
                "decision": "release",
                "reasons": [],
                "next_action": "present the assessed artifact",
                "presentable_as_user_answer": True,
            }
        )

    monkeypatch.setattr(quality_authorization, "decide_final_delivery", released)
    legacy = quality_authorization.decide_authorized_final_delivery(
        {}, authorized_quality, answer, trusted_key=KEY
    )
    narrowed = quality_authorization.decide_authorized_final_delivery(
        {},
        authorized_quality,
        answer,
        trusted_key=KEY,
        authorized_trust_assessment=trust_package,
        answer_trust_rollout_state="enforcement",
        answer_trust_promotion_metrics={
            "fabricated_value_detection_rate": 1.0,
            "citation_lineage_mismatch_detection_rate": 1.0,
            "minimum_human_review_capacity": 2,
            "planned_as_observed_escape_count": 0,
            "score_replay_mismatch_count": 0,
            "legacy_compatibility_failure_count": 0,
            "false_block_rate": 0.0,
            "p95_latency_ms": 1,
            "mean_artifact_bytes": 1000,
        },
    )
    assert legacy["decision"] == "release"
    assert narrowed["decision"] == "revise"
    assert narrowed["presentable_as_user_answer"] is False
    assert trust_package["digest"] in narrowed["reasons"][-1]


def test_blinded_frozen_calibration_reports_escape_false_block_and_agreement() -> None:
    """Verify blinded frozen calibration reports escape false block and agreement."""
    assessments = [
        {
            "case_id": "fabricated",
            "threat_class": "fabricated_value",
            "status": "blocked",
            "band": "blocked_untrusted",
            "score_interval": [0, 0],
        },
        {
            "case_id": "citation",
            "threat_class": "citation_laundering",
            "status": "blocked",
            "band": "blocked_untrusted",
            "score_interval": [0, 0],
        },
        {
            "case_id": "hypothesis",
            "threat_class": "bounded_hypothesis",
            "status": "assessed",
            "band": "substantiated",
            "score_interval": [70, 85],
        },
    ]
    reviews = [
        {
            "case_id": case_id,
            "reviewer_id": reviewer,
            "disposition": disposition,
            "reference_score": score,
            "reference_band": band,
        }
        for case_id, disposition, score, band in (
            ("fabricated", "blocked", 0, "blocked_untrusted"),
            ("citation", "blocked", 0, "blocked_untrusted"),
            ("hypothesis", "acceptable", 78, "substantiated"),
        )
        for reviewer in ("expert-a", "expert-b")
    ]
    calibration = calibrate_answer_trust(
        assessments,
        reviews,
        corpus_id="frozen-biomedical-calibration-v1",
        corpus_digest="sha256:" + "9" * 64,
        frozen=True,
        blinded=True,
        partition="validation",
    )
    assert calibration["status"] == "calibrated"
    assert calibration["metrics"]["unsupported_escape_recall"] == 1.0
    assert calibration["metrics"]["false_block_rate"] == 0.0
    assert calibration["metrics"]["interval_coverage"] == 1.0
    assert calibration["metrics"]["inter_reviewer_disagreement_rate"] == 0.0
    assert calibration["promotion_blockers"] == []
