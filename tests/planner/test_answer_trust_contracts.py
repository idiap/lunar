# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0

"""Strict schemas and semantic invariants for answer-trust artifacts.

This module protects expected behavior for the corresponding workflow, script, or repository surface. Key concepts: regression coverage, interface stability, and output integrity.
"""

from __future__ import annotations

import copy

from lunar_planner.answer_trust import (
    assess_answer_trust,
    build_answer_control_readiness,
)
from lunar_planner.contracts import (
    canonical_digest,
    load_answer_trust_policy,
    load_schema,
    seal_quality_contract,
    validate_contract,
)


def _digest(character: str) -> str:
    """Digest."""
    return "sha256:" + character * 64


def _protected(status: str = "preserved") -> dict:
    """Protected."""
    names = (
        "numbers",
        "units",
        "entities",
        "negation",
        "direction",
        "population",
        "specimen",
        "comparator",
        "endpoint",
        "time",
        "uncertainty",
        "missingness",
        "contradiction",
        "claim_ceiling",
    )
    return {name: {"status": status, "anchors": [f"field:{name}"]} for name in names}


def _receipt() -> dict:
    """Receipt."""
    return seal_quality_contract(
        {
            "schema_version": "lunar.planner.generative-transformation-receipt/v1",
            "receipt_id": "receipt-1",
            "observed_only": True,
            "operation_id": "edge-1",
            "provider": "producer-a",
            "provider_version": "1.0",
            "input_digests": [_digest("a")],
            "output_digest": _digest("b"),
            "allowed_evidence_ids": ["evidence-1"],
            "generated_ancestor_ids": [],
            "protected_field_checks": _protected(),
            "missing_fields": [],
            "lossy_fields": [],
            "abstained": False,
            "violations": [],
            "independent_verifier": {
                "id": "verifier-1",
                "provider": "verifier-b",
                "receipt_digest": _digest("c"),
            },
            "verification_status": "passed",
            "provenance_digest": _digest("d"),
        }
    )


def test_packaged_policy_is_data_only_digest_bound_and_registered() -> None:
    """Verify packaged policy is data only digest bound and registered."""
    policy = load_answer_trust_policy()
    assert policy["digest"] == canonical_digest(policy)
    assert policy["executable_payloads_allowed"] is False
    assert policy["dynamic_imports_allowed"] is False
    assert sum(policy["dimension_weights"].values()) == 1.0
    for version in (
        "lunar.planner.answer-control-readiness/v1",
        "lunar.planner.answer-trust-assessment/v1",
        "lunar.planner.claim-trust-assessment/v1",
        "lunar.planner.generative-transformation-receipt/v1",
    ):
        assert load_schema(version)["type"] == "object"


def test_readiness_is_score_free_prospective_and_digest_bound() -> None:
    """Verify readiness is score free prospective and digest bound."""
    readiness = build_answer_control_readiness(
        {"digest": _digest("a")}, {"digest": _digest("b"), "claim_atoms": []}
    )
    assert validate_contract(readiness).valid
    assert readiness["realized_trust_score"] is None
    assert readiness["polarity"] == "prospective_only"
    tampered = copy.deepcopy(readiness)
    tampered["realized_trust_score"] = 99
    tampered["digest"] = canonical_digest(tampered)
    assert not validate_contract(tampered).valid


def test_not_calculable_realized_assessment_validates_without_invented_evidence() -> (
    None
):
    """Verify not calculable realized assessment validates without invented evidence."""
    assessment = assess_answer_trust({}, [], [], [])
    report = validate_contract(assessment)
    assert report.valid, report.errors
    assert assessment["status"] == "not_calculable"
    assert assessment["score"] is None
    assert assessment["score_interval"] is None


def test_generative_receipt_rejects_self_review_and_protected_field_drift() -> None:
    """Verify generative receipt rejects self review and protected field drift."""
    assert validate_contract(_receipt()).valid
    self_reviewed = _receipt()
    self_reviewed["independent_verifier"]["provider"] = self_reviewed["provider"]
    self_reviewed["protected_field_checks"]["negation"]["status"] = "violated"
    self_reviewed["digest"] = canonical_digest(self_reviewed)
    errors = validate_contract(self_reviewed).errors
    assert any("producer-only" in error for error in errors)
    assert any("protected-field violation" in error for error in errors)


def test_realized_assessment_rejects_generated_ancestry_laundered_as_external() -> None:
    """Verify realized assessment rejects generated ancestry laundered as external."""
    assessment = assess_answer_trust({}, [], [], [])
    assessment["evidence_atoms"] = [
        {
            "evidence_id": "evidence-1",
            "origin": "external",
            "authorized": True,
            "content_digest": _digest("e"),
            "locator": "table/1",
            "observed_consumed": True,
            "independence_cluster": "cluster-1",
            "generated_ancestor_ids": ["generated-1"],
        }
    ]
    assessment["digest"] = canonical_digest(assessment)
    assert any(
        "generated ancestry cannot be recast" in error
        for error in validate_contract(assessment).errors
    )
