# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0

"""TEST/BENCHMARK ONLY quality-attestation helper.

This deterministic key is public and must never be used by production MCP
deployments.  It exists solely so offline repository fixtures exercise the same
authenticated assessment path without pretending to establish real trust.
"""

from __future__ import annotations

from typing import Any

from lunar_planner.quality_authorization import (
    attest_plan_review_result,
    attest_anchor_manifest,
    attest_deterministic_check,
    attest_evaluator_results,
    issue_evaluator_authorization,
    issue_plan_review_authorization,
    verify_authorized_plan_review,
)

TEST_ONLY_QUALITY_ATTESTATION_KEY = b"lunar-public-test-fixture-key-not-for-production"


def build_test_only_plan_review_evidence(
    plan: dict[str, Any],
    review: dict[str, Any],
    *,
    criterion_producer_id: str,
    nonce: str,
    evaluation_receipts: list[dict[str, Any]] | None = None,
    semantic_review_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a signed plan-review package for an offline fixture."""

    reviewer = dict(review["reviewer"])
    if evaluation_receipts is None:
        evaluation_receipts = [
            {
                "phase": "plan_review",
                "request_digest": plan["digest"],
                "status": review["verdict"],
                "evaluator": reviewer,
                "evidence_class": "harness_conformance_only",
                "synthetic": True,
            }
            for _index in range(
                2 if plan.get("risk_tier") in {"complex", "human_authority"} else 1
            )
        ]
    semantic_review = {
        "plan_digest": plan["digest"],
        "verdict": review["verdict"],
        "independent": review["independent"],
        "reviewer_id": reviewer["id"],
        "checks": review.get("checks", {}),
        "findings": review.get("findings", []),
        "evaluation_receipts": list(evaluation_receipts),
    }
    if semantic_review_evidence is not None:
        semantic_review["primary_proposal"] = dict(
            semantic_review_evidence["primary_proposal"]
        )
        semantic_review["independent_critic_result"] = dict(
            semantic_review_evidence["independent_critic_result"]
        )
    authorization = issue_plan_review_authorization(
        plan,
        reviewer=reviewer,
        criterion_producer_id=criterion_producer_id,
        nonce=nonce,
        trusted_key=TEST_ONLY_QUALITY_ATTESTATION_KEY,
    )
    attestation = attest_plan_review_result(
        authorization,
        semantic_review,
        trusted_key=TEST_ONLY_QUALITY_ATTESTATION_KEY,
    )
    return {
        "review_authorization": authorization,
        "review_attestation": attestation,
        "semantic_review": semantic_review,
        "authorized_review": verify_authorized_plan_review(
            plan,
            semantic_review,
            reviewer=reviewer,
            criterion_producer_id=criterion_producer_id,
            authorization=authorization,
            result_attestation=attestation,
            trusted_key=TEST_ONLY_QUALITY_ATTESTATION_KEY,
        ),
    }


def build_test_only_assessment_evidence(
    plan: dict[str, Any],
    artifact: Any,
    criterion_results: list[dict[str, Any]],
    *,
    evaluator: dict[str, Any],
    producer_id: str | None,
    nonce: str,
) -> dict[str, Any]:
    """Create authenticated fixture receipts with an explicitly non-secret key."""

    authorization = issue_evaluator_authorization(
        plan,
        artifact,
        evaluator=evaluator,
        producer_id=producer_id,
        nonce=nonce,
        trusted_key=TEST_ONLY_QUALITY_ATTESTATION_KEY,
    )
    artifact_anchors = {
        str(anchor)
        for row in criterion_results
        for anchor in row.get("artifact_anchors", ())
    }
    source_anchors = {
        str(anchor)
        for row in criterion_results
        for anchor in row.get("source_anchors", ())
    }
    manifest = attest_anchor_manifest(
        authorization,
        artifact_anchors=artifact_anchors,
        source_anchors=source_anchors,
        trusted_key=TEST_ONLY_QUALITY_ATTESTATION_KEY,
    )
    deterministic_receipts = [
        attest_deterministic_check(
            authorization,
            criterion_id=str(criterion["criterion_id"]),
            verdict=str(
                next(
                    row.get("verdict", "inconclusive")
                    for row in criterion_results
                    if row.get("criterion_id") == criterion["criterion_id"]
                )
            ),
            artifact_anchors=next(
                row.get("artifact_anchors", ())
                for row in criterion_results
                if row.get("criterion_id") == criterion["criterion_id"]
            ),
            source_anchors=next(
                row.get("source_anchors", ())
                for row in criterion_results
                if row.get("criterion_id") == criterion["criterion_id"]
            ),
            verifier={
                "id": "test-only-deterministic-fixture-verifier",
                "configuration": "v1",
            },
            trusted_key=TEST_ONLY_QUALITY_ATTESTATION_KEY,
        )
        for criterion in plan.get("criteria", ())
        if criterion.get("evaluator_mode") in {"deterministic", "hybrid"}
    ]
    return {
        "authorization": authorization,
        "result_attestation": attest_evaluator_results(
            authorization,
            criterion_results,
            manifest,
            trusted_key=TEST_ONLY_QUALITY_ATTESTATION_KEY,
        ),
        "deterministic_receipts": deterministic_receipts,
        "anchor_manifest": manifest,
    }
