# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0

"""Authenticated quality-plan review helpers for planner tests only.

This module protects expected behavior for the corresponding workflow, script, or repository surface. Key concepts: regression coverage, interface stability, and output integrity.
"""

from __future__ import annotations

from typing import Any

from lunar_planner.quality_authorization import (
    attest_plan_review_result,
    issue_plan_review_authorization,
    verify_authorized_plan_review,
)

TEST_ONLY_QUALITY_KEY = b"lunar-public-test-fixture-key-not-for-production"


def authorize_test_plan_review(
    plan: dict[str, Any], review: dict[str, Any], producer_id: str
) -> dict[str, Any]:
    """Authorize test plan review."""
    reviewer = dict(review["reviewer"])
    semantic_review = {
        "plan_digest": plan["digest"],
        "verdict": review["verdict"],
        "independent": review["independent"],
        "reviewer_id": reviewer["id"],
        "checks": review.get("checks", {}),
        "findings": review.get("findings", []),
        "evaluation_receipts": [
            {
                "phase": "plan_review",
                "request_digest": plan["digest"],
                "status": review["verdict"],
                "evaluator": reviewer,
            }
            for _index in range(
                2 if plan.get("risk_tier") in {"complex", "human_authority"} else 1
            )
        ],
    }
    authorization = issue_plan_review_authorization(
        plan,
        reviewer=reviewer,
        criterion_producer_id=producer_id,
        nonce=f"test-{plan['digest'][-12:]}",
        trusted_key=TEST_ONLY_QUALITY_KEY,
    )
    attestation = attest_plan_review_result(
        authorization, semantic_review, trusted_key=TEST_ONLY_QUALITY_KEY
    )
    return verify_authorized_plan_review(
        plan,
        semantic_review,
        reviewer=reviewer,
        criterion_producer_id=producer_id,
        authorization=authorization,
        result_attestation=attestation,
        trusted_key=TEST_ONLY_QUALITY_KEY,
    )
