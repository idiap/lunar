# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0

"""Tests for Workflow economics calibration.

This module protects expected behavior for the corresponding workflow, script, or repository surface. Key concepts: regression coverage, interface stability, and output integrity.
"""

from __future__ import annotations

import pytest

from lunar_planner.workflow_economics_calibration import (
    build_resource_profile,
    calibrate_workflow_effort,
)


def estimate(case_id="case-1"):
    """Estimate."""
    return {
        "case_id": case_id,
        "headline": {
            "manual_person_hours": {"p10": 8, "p50": 10, "p90": 12},
            "assisted_person_hours": {"p10": 3, "p50": 4, "p90": 6},
        },
    }


def reviews(quality=True, manual=10, assisted=4):
    """Reviews."""
    return [
        {
            "case_id": "case-1",
            "reviewer_id": reviewer,
            "reviewer_role": "domain expert",
            "experience_years": 8,
            "output_quality_equivalent": quality,
            "observed_manual_person_hours": manual,
            "observed_assisted_person_hours": assisted,
        }
        for reviewer in ("r1", "r2")
    ]


def test_effort_calibration_requires_blinded_frozen_quality_matched_evidence():
    """Verify effort calibration requires blinded frozen quality matched evidence."""
    result = calibrate_workflow_effort(
        [estimate()],
        reviews(),
        corpus_id="c",
        corpus_digest="sha256:c",
        frozen=True,
        blinded=True,
        partition="sealed_validation",
    )
    assert result["status"] == "calibrated"
    assert result["metrics"]["manual_interval_coverage"] == 1
    assert result["metrics"]["assisted_interval_coverage"] == 1
    assert result["metrics"]["false_positive_savings_rate"] == 0


@pytest.mark.parametrize(
    "frozen,blinded,partition",
    [
        (False, True, "sealed_validation"),
        (True, False, "sealed_validation"),
        (True, True, "release_candidate"),
        (True, True, "displayed_evaluation"),
    ],
)
def test_effort_calibration_promotion_gates(frozen, blinded, partition):
    """Verify effort calibration promotion gates."""
    result = calibrate_workflow_effort(
        [estimate()],
        reviews(),
        corpus_id="c",
        corpus_digest="sha256:c",
        frozen=frozen,
        blinded=blinded,
        partition=partition,
    )
    assert result["status"] == "insufficient_calibration_evidence"
    assert result["promotion_blockers"]


def test_quality_mismatch_never_counts_as_time_savings():
    """Verify quality mismatch never counts as time savings."""
    result = calibrate_workflow_effort(
        [estimate()],
        reviews(quality=False),
        corpus_id="c",
        corpus_digest="sha256:c",
        frozen=True,
        blinded=True,
        partition="sealed_validation",
    )
    assert result["metrics"]["quality_parity_eligible_cases"] == 0
    assert any("quality" in blocker for blocker in result["promotion_blockers"])


def test_calibration_requires_reviewer_role_and_experience():
    """Verify calibration requires reviewer role and experience."""
    incomplete = reviews()
    incomplete[0].pop("reviewer_role")
    with pytest.raises(ValueError, match="role and experience"):
        calibrate_workflow_effort(
            [estimate()],
            incomplete,
            corpus_id="c",
            corpus_digest="sha256:c",
            frozen=True,
            blinded=True,
            partition="sealed_validation",
        )


def test_false_positive_savings_and_residual_underestimate_are_detected():
    """Verify false positive savings and residual underestimate are detected."""
    result = calibrate_workflow_effort(
        [estimate()],
        reviews(manual=3, assisted=8),
        corpus_id="c",
        corpus_digest="sha256:c",
        frozen=True,
        blinded=True,
        partition="sealed_validation",
    )
    assert result["metrics"]["false_positive_savings_rate"] == 1
    assert result["metrics"]["residual_effort_underestimation_rate"] == 1
    assert result["status"] == "insufficient_calibration_evidence"


def observations(count=10, revision="v1"):
    """Observations."""
    return [
        {
            "observed_at": "2026-08-20T00:00:00Z",
            "observed_value": index,
            "estimated_value": index + 1,
            "privacy_cohort_id": f"cohort-{index % 5}",
            "provider_revision": revision,
        }
        for index in range(count)
    ]


def test_resource_profile_is_privacy_filtered_and_uses_absolute_zero_error():
    """Verify resource profile is privacy filtered and uses absolute zero error."""
    profile = build_resource_profile(
        observations(), profile_id="p", as_of="2026-08-30", provider_revision="v1"
    )
    assert profile["status"] == "matched_profile"
    assert profile["calibration"]["mean_absolute_error_for_actual_zero"] == 1
    assert (
        profile["distribution"]["p10"]
        <= profile["distribution"]["p50"]
        <= profile["distribution"]["p90"]
    )
    bad = observations()
    bad[0]["prompt"] = "secret"
    with pytest.raises(ValueError, match="prohibited"):
        build_resource_profile(bad, profile_id="p", as_of="2026-08-30")


def test_resource_profile_reports_holdout_coverage_retry_overrun_and_invoice_error():
    """Verify resource profile reports holdout coverage retry overrun and invoice error."""
    rows = observations()
    for row in rows:
        observed = row["observed_value"]
        row.update(
            {
                "estimated_low": max(observed - 1, 0),
                "estimated_high": observed + 1,
                "estimated_retries": 1,
                "observed_retries": 1,
                "estimated_cost": 2,
                "estimated_cost_low": 1,
                "estimated_cost_high": 3,
                "observed_cost": 2,
                "invoice_cost": 2.5,
            }
        )
    calibration = build_resource_profile(rows, profile_id="p", as_of="2026-08-30")[
        "calibration"
    ]
    assert calibration["interval_coverage"] == 1
    assert calibration["retry_mean_absolute_error"] == 0
    assert calibration["cost_interval_coverage"] == 1
    assert calibration["mean_absolute_invoice_discrepancy"] == 0.5


def test_sparse_stale_and_revision_drift_profiles_fall_back():
    """Verify sparse stale and revision drift profiles fall back."""
    sparse = build_resource_profile(observations(2), profile_id="p", as_of="2026-08-30")
    assert sparse["status"] == "fallback_required"
    drift = build_resource_profile(
        observations(revision="old"),
        profile_id="p",
        as_of="2026-08-30",
        provider_revision="new",
    )
    assert drift["status"] == "fallback_required"
    assert drift["excluded_revision_mismatch_count"] == 10
