# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0

"""Tests for Answer trust.

This module protects expected behavior for the corresponding workflow, script, or repository surface. Key concepts: regression coverage, interface stability, and output integrity.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from lunar_planner.answer_trust import (
    AnswerTrustError,
    assess_answer_trust,
    build_answer_control_readiness,
    build_trust_card,
    invalidate_answer_trust,
)


def _digest(value: object) -> str:
    """Digest."""
    rendered = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(rendered.encode()).hexdigest()


def _answer(*component_ids: str) -> dict:
    """Answer."""
    return {
        "digest": _digest({"text": "exact released answer"}),
        "execution_state": "observed",
        "components": [{"component_id": value} for value in component_ids],
    }


def _claim(
    claim_id: str = "claim-1", component_id: str = "component-1", **updates: object
) -> dict:
    """Claim."""
    row = {
        "claim_id": claim_id,
        "claim_class": "material_factual",
        "component_ids": [component_id],
        "evidence_ids": ["evidence-1"],
        "uncertainty_preserved": 1.0,
        "conflicts_disclosed": 1.0,
        "missingness_preserved": 1.0,
    }
    row.update(updates)
    return row


def _evidence(evidence_id: str = "evidence-1", **updates: object) -> dict:
    """Evidence."""
    row = {
        "evidence_id": evidence_id,
        "origin": "external",
        "authorized": True,
        "observed": True,
        "observed_consumed": True,
        "content_digest": _digest({"evidence": evidence_id}),
        "locator": "table 2, row 4",
        "authority": 1.0,
        "directness": 1.0,
        "applicability": 1.0,
        "independence_cluster": evidence_id,
    }
    row.update(updates)
    return row


def _edge(
    evidence_id: str = "evidence-1",
    component_id: str = "component-1",
    **updates: object,
) -> dict:
    """Edge."""
    row = {
        "edge_id": "edge-1",
        "input_ids": [evidence_id],
        "output_id": component_id,
        "kind": "deterministic",
        "observed": True,
        "verified": True,
    }
    row.update(updates)
    return row


def test_readiness_is_prospective_score_free_and_non_mutating() -> None:
    """Verify readiness is prospective score free and non mutating."""
    plan = {"digest": _digest({"plan": 1}), "nodes": [{"node_id": "n1"}]}
    verification = {
        "digest": _digest({"verification": 1}),
        "claim_atoms": [
            {"claim_id": "claim-1", "assertion_kind": "scientific_synthesis"}
        ],
        "derivation_edges": [
            {"edge_id": "g1", "kind": "generative", "plan_location": "/nodes/n1"}
        ],
    }

    readiness = build_answer_control_readiness(plan, verification)

    assert readiness["polarity"] == "prospective_only"
    assert readiness["realized_trust_score"] is None
    assert readiness["attainable_control_band"] == "guarded"
    assert readiness["mutates_initial_plan"] is False
    assert {finding["finding_id"] for finding in readiness["findings"]} == {
        "readiness:g1:allowed_evidence_envelope",
        "readiness:g1:independent_fidelity_review",
        "readiness:g1:protected_field_checks",
    }
    assert plan == {"digest": _digest({"plan": 1}), "nodes": [{"node_id": "n1"}]}


def test_planned_answer_and_absent_retrospective_inputs_are_not_calculable() -> None:
    """Verify planned answer and absent retrospective inputs are not calculable."""
    planned = assess_answer_trust(
        {**_answer("component-1"), "execution_state": "planned"},
        [_claim()],
        [_evidence()],
        [_edge()],
    )
    absent = assess_answer_trust(_answer("component-1"), [_claim()], [], [])

    assert planned["status"] == "not_calculable"
    assert planned["score"] is None
    assert absent["status"] == "not_calculable"
    assert (
        "observed evidence and lineage inputs are absent" in absent["blocking_reasons"]
    )


def test_fully_grounded_preserved_claim_reaches_high_control() -> None:
    """Verify fully grounded preserved claim reaches high control."""
    assessment = assess_answer_trust(
        _answer("component-1"),
        [_claim(release_critical=True)],
        [_evidence()],
        [_edge()],
    )

    assert assessment["status"] == "assessed"
    assert assessment["score"] == pytest.approx(100.0)
    assert assessment["score_interval"] == pytest.approx([100.0, 100.0])
    assert assessment["band"] == "high_control"
    assert assessment["diagnostics"]["grounded_material_claim_coverage"] == 1.0
    assert assessment["evidence_atoms"][0]["evidence_id"] == "evidence-1"
    assert assessment["derivation_edges"][0]["output_id"] == "component-1"


@pytest.mark.parametrize(
    "origin", ["model_memory", "generated", "retrieval_hint", "planned"]
)
def test_non_evidence_origin_cannot_be_averaged_away(origin: str) -> None:
    """Verify non evidence origin cannot be averaged away."""
    assessment = assess_answer_trust(
        _answer("component-1"), [_claim()], [_evidence(origin=origin)], [_edge()]
    )

    row = assessment["claim_assessments"][0]
    assert assessment["status"] == "blocked"
    assert assessment["score"] == 0.0
    assert row["score"] == 0.0
    assert "non_evidence_origin_only" in {gate["code"] for gate in row["gates"]}


def test_real_citation_without_consumed_lineage_scores_zero() -> None:
    """Verify real citation without consumed lineage scores zero."""
    assessment = assess_answer_trust(
        _answer("component-1"),
        [_claim()],
        [_evidence()],
        [_edge(component_id="different-component")],
    )

    row = assessment["claim_assessments"][0]
    assert row["score"] == 0.0
    assert row["citation_lineage_mismatch"] is True
    assert assessment["diagnostics"]["citation_lineage_mismatch_rate"] == 1.0


def test_uncontained_generative_edge_is_capped_and_preservation_is_audited() -> None:
    """Verify uncontained generative edge is capped and preservation is audited."""
    generative = _edge(kind="generative", verified=False)
    weak = assess_answer_trust(
        _answer("component-1"), [_claim()], [_evidence()], [generative]
    )
    controlled = assess_answer_trust(
        _answer("component-1"),
        [_claim()],
        [_evidence()],
        [generative],
        generative_receipts=[
            {
                "edge_id": "edge-1",
                "observed": True,
                "allowed_evidence_ids": ["evidence-1"],
                "independent_verifier_id": "verifier-2",
                "protected_fields": {
                    "value": 1.0,
                    "unit": 1.0,
                    "negation": 1.0,
                    "missingness": 1.0,
                },
                "violations": [],
            }
        ],
    )

    weak_claim = weak["claim_assessments"][0]
    assert weak_claim["score_interval"][1] <= 25.0
    assert "missing_generative_receipt" in {cap["code"] for cap in weak_claim["caps"]}
    assert controlled["score"] == pytest.approx(100.0)
    assert controlled["band"] == "high_control"


def test_observed_computation_receipt_can_close_deterministic_preservation() -> None:
    """Verify observed computation receipt can close deterministic preservation."""
    edge = _edge(verified=None)
    unknown = assess_answer_trust(
        _answer("component-1"), [_claim()], [_evidence()], [edge]
    )
    recomputed = assess_answer_trust(
        _answer("component-1"),
        [_claim()],
        [_evidence()],
        [edge],
        computation_receipts=[
            {"edge_id": "edge-1", "observed": True, "recomputation_passed": True}
        ],
    )

    assert unknown["status"] == "insufficient_evidence"
    assert recomputed["status"] == "assessed"
    assert recomputed["score"] == pytest.approx(100.0)


def test_unknown_dimension_produces_interval_and_insufficient_evidence() -> None:
    """Verify unknown dimension produces interval and insufficient evidence."""
    uncertain_claim = _claim()
    uncertain_claim.pop("uncertainty_preserved")
    uncertain_claim.pop("conflicts_disclosed")
    uncertain_claim.pop("missingness_preserved")

    assessment = assess_answer_trust(
        _answer("component-1"), [uncertain_claim], [_evidence()], [_edge()]
    )

    assert assessment["status"] == "insufficient_evidence"
    assert assessment["score"] is None
    assert assessment["score_interval"][1] - assessment["score_interval"][0] > 20


def test_critical_claim_caps_answer_despite_strong_minor_claim() -> None:
    """Verify critical claim caps answer despite strong minor claim."""
    claims = [
        _claim("critical", "headline", evidence_ids=["memory"], release_critical=True),
        _claim("background", "context", evidence_ids=["evidence-1"]),
    ]
    evidence = [_evidence(), _evidence("memory", origin="model_memory")]
    edges = [
        _edge(component_id="context"),
        _edge("memory", "headline", edge_id="edge-critical"),
    ]

    assessment = assess_answer_trust(
        _answer("headline", "context"), claims, evidence, edges
    )

    assert assessment["status"] == "blocked"
    assert assessment["score"] == 0.0
    assert assessment["band"] == "blocked_untrusted"
    assert assessment["diagnostics"]["weakest_claim_ids"][0] == "critical"


def test_order_invariance_exemptions_invalidation_and_trust_card() -> None:
    """Verify order invariance exemptions invalidation and trust card."""
    claims = [
        _claim(),
        _claim(
            "constraint",
            "note",
            claim_class="user_constraint",
            evidence_ids=[],
            exempt=True,
        ),
    ]
    evidence = [_evidence(), _evidence("irrelevant")]
    assessment = assess_answer_trust(
        _answer("component-1", "note"), claims, evidence, [_edge()]
    )
    permuted = assess_answer_trust(
        _answer("component-1", "note"),
        list(reversed(claims)),
        list(reversed(evidence)),
        [_edge()],
    )

    assert assessment["digest"] == permuted["digest"]
    assert assessment["material_claim_coverage"] == 1.0
    assert assessment["exemptions"] == [
        {"claim_id": "constraint", "reason": "user_constraint"}
    ]

    valid = invalidate_answer_trust(assessment, assessment["binding"])
    invalid = invalidate_answer_trust(
        assessment, {"answer_digest": _digest({"changed": True})}
    )
    assert valid["valid"] is True
    assert invalid["valid"] is False
    assert invalid["reentry_owners"] == ["answer materializer"]

    card = build_trust_card(assessment)
    assert card["assessment_digest"] == assessment["digest"]
    assert "not a probability" in card["interpretation"]
    assert "dimensions" not in card["critical_weaknesses"][0]


def test_policy_digest_mismatch_and_duplicate_claim_ids_fail_closed() -> None:
    """Verify policy digest mismatch and duplicate claim ids fail closed."""
    with pytest.raises(AnswerTrustError, match="policy digest"):
        assess_answer_trust(
            _answer("component-1"),
            [_claim()],
            [_evidence()],
            [_edge()],
            scoring_policy_digest="sha256:bad",
        )
    with pytest.raises(AnswerTrustError, match="unique"):
        assess_answer_trust(
            _answer("component-1"), [_claim(), _claim()], [_evidence()], [_edge()]
        )
