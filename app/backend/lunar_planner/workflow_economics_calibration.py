# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0

"""Calibration utilities for planner workflow-economics profiles.

Calibration evidence must be frozen, blinded, output-quality matched, and kept
separate from release candidates.  These pure functions only evaluate supplied
records; they do not tune profiles or turn advisory economics on.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timezone
from typing import Any


def _digest(value: Any) -> str:
    """Digest."""
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _ratio(numerator: float, denominator: int) -> float | None:
    """Ratio."""
    return numerator / denominator if denominator else None


def _median(values: Sequence[float]) -> float | None:
    """Median."""
    ordered = sorted(values)
    if not ordered:
        return None
    middle = len(ordered) // 2
    return (
        ordered[middle]
        if len(ordered) % 2
        else (ordered[middle - 1] + ordered[middle]) / 2
    )


def calibrate_workflow_effort(
    estimates: Sequence[Mapping[str, Any]],
    expert_reviews: Sequence[Mapping[str, Any]],
    *,
    corpus_id: str,
    corpus_digest: str,
    frozen: bool,
    blinded: bool,
    partition: str,
    minimum_reviewers_per_case: int = 2,
    minimum_interval_coverage: float = 0.8,
    maximum_false_positive_savings_rate: float = 0.05,
    maximum_residual_underestimation_rate: float = 0.1,
) -> dict[str, Any]:
    """Evaluate effort intervals against matched, independently reviewed work."""
    predicted = {str(row.get("case_id", "")): dict(row) for row in estimates}
    if "" in predicted or len(predicted) != len(estimates):
        raise ValueError("estimate case IDs must be non-empty and unique")
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    pairs: set[tuple[str, str]] = set()
    for raw in expert_reviews:
        row = dict(raw)
        case_id, reviewer_id = str(row.get("case_id", "")), str(
            row.get("reviewer_id", "")
        )
        if not case_id or not reviewer_id:
            raise ValueError("reviews require case_id and reviewer_id")
        if not row.get("reviewer_role") or row.get("experience_years") is None:
            raise ValueError("reviews require reviewer role and experience")
        if float(row["experience_years"]) < 0:
            raise ValueError("reviewer experience cannot be negative")
        if case_id not in predicted:
            raise ValueError(f"review references unknown case: {case_id}")
        if (case_id, reviewer_id) in pairs:
            raise ValueError("one reviewer may submit only one review per case")
        pairs.add((case_id, reviewer_id))
        grouped[case_id].append(row)

    eligible = covered_manual = covered_assisted = 0
    false_positive = residual_under = 0
    manual_errors: list[float] = []
    assisted_errors: list[float] = []
    disagreements = 0
    quality_mismatch: list[str] = []
    insufficient: list[str] = []
    adjudication: dict[str, Any] = {}
    for case_id in sorted(predicted):
        rows = grouped.get(case_id, [])
        if len(rows) < minimum_reviewers_per_case:
            insufficient.append(case_id)
        quality_votes = Counter(
            bool(row.get("output_quality_equivalent", False)) for row in rows
        )
        if len(quality_votes) > 1:
            disagreements += 1
        quality = quality_votes.get(True, 0) > quality_votes.get(False, 0)
        manual_values = [
            float(row["observed_manual_person_hours"])
            for row in rows
            if row.get("observed_manual_person_hours") is not None
        ]
        assisted_values = [
            float(row["observed_assisted_person_hours"])
            for row in rows
            if row.get("observed_assisted_person_hours") is not None
        ]
        manual_observed, assisted_observed = _median(manual_values), _median(
            assisted_values
        )
        estimate = predicted[case_id]
        headline = estimate.get("headline") or {}
        manual_interval = headline.get("manual_person_hours") or {}
        assisted_interval = headline.get("assisted_person_hours") or {}
        if not quality:
            quality_mismatch.append(case_id)
        elif manual_observed is not None and assisted_observed is not None:
            eligible += 1
            covered_manual += int(
                float(manual_interval.get("p10", math.inf))
                <= manual_observed
                <= float(manual_interval.get("p90", -math.inf))
            )
            covered_assisted += int(
                float(assisted_interval.get("p10", math.inf))
                <= assisted_observed
                <= float(assisted_interval.get("p90", -math.inf))
            )
            manual_p50 = float(manual_interval.get("p50", math.nan))
            assisted_p50 = float(assisted_interval.get("p50", math.nan))
            if math.isfinite(manual_p50):
                manual_errors.append(manual_p50 - manual_observed)
            if math.isfinite(assisted_p50):
                assisted_errors.append(assisted_p50 - assisted_observed)
            predicted_saved = manual_p50 - assisted_p50
            observed_saved = manual_observed - assisted_observed
            false_positive += int(predicted_saved > 0 >= observed_saved)
            residual_under += int(
                float(assisted_interval.get("p90", -math.inf)) < assisted_observed
            )
        adjudication[case_id] = {
            "reviewer_count": len(rows),
            "output_quality_equivalent": quality,
            "observed_manual_person_hours": manual_observed,
            "observed_assisted_person_hours": assisted_observed,
        }
    metrics = {
        "manual_interval_coverage": _ratio(covered_manual, eligible),
        "assisted_interval_coverage": _ratio(covered_assisted, eligible),
        "false_positive_savings_rate": _ratio(false_positive, eligible),
        "residual_effort_underestimation_rate": _ratio(residual_under, eligible),
        "manual_median_bias_hours": _median(manual_errors),
        "assisted_median_bias_hours": _median(assisted_errors),
        "inter_reviewer_disagreement_rate": _ratio(disagreements, len(predicted)),
        "quality_parity_eligible_cases": eligible,
    }
    blockers: list[str] = []
    if not frozen:
        blockers.append("calibration corpus is not frozen")
    if not blinded:
        blockers.append("calibration review is not blinded")
    if partition in {"release_candidate", "displayed_evaluation"}:
        blockers.append(
            "displayed or release-candidate cases cannot be used for tuning"
        )
    if insufficient:
        blockers.append(f"insufficient independent reviewers for cases: {insufficient}")
    if quality_mismatch:
        blockers.append(f"output-quality parity failed for cases: {quality_mismatch}")
    if not eligible:
        blockers.append(
            "no quality-equivalent cases have complete matched effort observations"
        )
    if (
        metrics["manual_interval_coverage"] is not None
        and metrics["manual_interval_coverage"] < minimum_interval_coverage
    ):
        blockers.append("manual interval coverage is below threshold")
    if (
        metrics["assisted_interval_coverage"] is not None
        and metrics["assisted_interval_coverage"] < minimum_interval_coverage
    ):
        blockers.append("assisted interval coverage is below threshold")
    if (
        metrics["false_positive_savings_rate"] is not None
        and metrics["false_positive_savings_rate"] > maximum_false_positive_savings_rate
    ):
        blockers.append("false-positive savings rate exceeds threshold")
    if (
        metrics["residual_effort_underestimation_rate"] is not None
        and metrics["residual_effort_underestimation_rate"]
        > maximum_residual_underestimation_rate
    ):
        blockers.append("residual-effort underestimation exceeds threshold")
    result = {
        "schema_version": "lunar.planner.workflow-effort-calibration/v1",
        "corpus_id": corpus_id,
        "corpus_digest": corpus_digest,
        "frozen": frozen,
        "blinded": blinded,
        "partition": partition,
        "estimate_count": len(predicted),
        "review_count": len(expert_reviews),
        "thresholds": {
            "minimum_reviewers_per_case": minimum_reviewers_per_case,
            "minimum_interval_coverage": minimum_interval_coverage,
            "maximum_false_positive_savings_rate": maximum_false_positive_savings_rate,
            "maximum_residual_underestimation_rate": maximum_residual_underestimation_rate,
        },
        "metrics": metrics,
        "adjudication": adjudication,
        "promotion_blockers": blockers,
        "status": "calibrated" if not blockers else "insufficient_calibration_evidence",
        "policy_tuned_on_evaluation_cases": False,
    }
    result["digest"] = _digest(result)
    return result


def build_resource_profile(
    observations: Sequence[Mapping[str, Any]],
    *,
    profile_id: str,
    as_of: str,
    minimum_sample_size: int = 10,
    minimum_privacy_cohort: int = 5,
    maximum_age_days: int = 180,
    provider_revision: str | None = None,
) -> dict[str, Any]:
    """Build a privacy-filtered component/provider usage profile.

    Raw prompts, responses, identities, and patient-level data are rejected;
    only aggregate numeric usage/cost/error measurements are retained.
    """
    prohibited = {
        "prompt",
        "response",
        "hidden_reasoning",
        "credential",
        "patient_row",
        "user_id",
        "person_id",
    }
    rows = [dict(row) for row in observations]
    for row in rows:
        present = prohibited & set(row)
        if present:
            raise ValueError(
                f"resource observations contain prohibited fields: {sorted(present)}"
            )
    today = date.fromisoformat(as_of[:10])
    eligible = []
    stale = 0
    revision_mismatch = 0
    for row in rows:
        timestamp = datetime.fromisoformat(
            str(row["observed_at"]).replace("Z", "+00:00")
        )
        observed_date = timestamp.astimezone(timezone.utc).date()
        if (today - observed_date).days > maximum_age_days:
            stale += 1
            continue
        if provider_revision and row.get("provider_revision") != provider_revision:
            revision_mismatch += 1
            continue
        eligible.append(row)
    values = [float(row["observed_value"]) for row in eligible]
    cohort_ids = {
        str(row.get("privacy_cohort_id", ""))
        for row in eligible
        if row.get("privacy_cohort_id")
    }
    blockers = []
    if len(eligible) < minimum_sample_size:
        blockers.append("sample is sparse")
    if len(cohort_ids) < minimum_privacy_cohort:
        blockers.append("privacy cohort threshold is not met")
    if revision_mismatch:
        blockers.append("provider revision drift requires a new or wider profile")
    ordered = sorted(values)

    def quantile(q: float) -> float | None:
        """Quantile."""
        if not ordered:
            return None
        index = q * (len(ordered) - 1)
        lo, hi = math.floor(index), math.ceil(index)
        return (
            ordered[lo]
            if lo == hi
            else ordered[lo] + (ordered[hi] - ordered[lo]) * (index - lo)
        )

    zero_errors = [
        abs(float(row.get("estimated_value", 0)) - float(row["observed_value"]))
        for row in eligible
        if float(row["observed_value"]) == 0
    ]
    nonzero_errors = [
        abs(float(row.get("estimated_value", 0)) - float(row["observed_value"]))
        / abs(float(row["observed_value"]))
        for row in eligible
        if float(row["observed_value"]) != 0
    ]
    interval_rows = [
        row
        for row in eligible
        if row.get("estimated_low") is not None
        and row.get("estimated_high") is not None
    ]
    interval_coverage = (
        sum(
            float(row["estimated_low"])
            <= float(row["observed_value"])
            <= float(row["estimated_high"])
            for row in interval_rows
        )
        / len(interval_rows)
        if interval_rows
        else None
    )
    retry_rows = [
        row
        for row in eligible
        if row.get("observed_retries") is not None
        and row.get("estimated_retries") is not None
    ]
    retry_mae = (
        sum(
            abs(float(row["estimated_retries"]) - float(row["observed_retries"]))
            for row in retry_rows
        )
        / len(retry_rows)
        if retry_rows
        else None
    )
    overrun_rows = [row for row in eligible if row.get("estimated_value") is not None]
    overrun_rate = (
        sum(
            float(row["observed_value"]) > float(row["estimated_value"])
            for row in overrun_rows
        )
        / len(overrun_rows)
        if overrun_rows
        else None
    )
    cost_rows = [
        row
        for row in eligible
        if row.get("estimated_cost") is not None
        and row.get("observed_cost") is not None
    ]
    cost_coverage = (
        sum(
            float(row.get("estimated_cost_low", row["estimated_cost"]))
            <= float(row["observed_cost"])
            <= float(row.get("estimated_cost_high", row["estimated_cost"]))
            for row in cost_rows
        )
        / len(cost_rows)
        if cost_rows
        else None
    )
    invoice_rows = [
        row
        for row in eligible
        if row.get("observed_cost") is not None and row.get("invoice_cost") is not None
    ]
    invoice_discrepancy = (
        sum(
            abs(float(row["invoice_cost"]) - float(row["observed_cost"]))
            for row in invoice_rows
        )
        / len(invoice_rows)
        if invoice_rows
        else None
    )
    result = {
        "schema_version": "lunar.planner.workflow-resource-profile/v1",
        "profile_id": profile_id,
        "as_of": as_of,
        "provider_revision": provider_revision,
        "status": "matched_profile" if not blockers else "fallback_required",
        "sample_size": len(eligible),
        "excluded_stale_count": stale,
        "excluded_revision_mismatch_count": revision_mismatch,
        "privacy_cohort_count": len(cohort_ids),
        "distribution": {
            "p10": quantile(0.1),
            "p50": quantile(0.5),
            "p90": quantile(0.9),
        },
        "calibration": {
            "mean_absolute_error_for_actual_zero": (
                sum(zero_errors) / len(zero_errors) if zero_errors else None
            ),
            "mean_absolute_percentage_error_for_nonzero": (
                sum(nonzero_errors) / len(nonzero_errors) if nonzero_errors else None
            ),
            "interval_coverage": interval_coverage,
            "retry_mean_absolute_error": retry_mae,
            "overrun_rate": overrun_rate,
            "cost_interval_coverage": cost_coverage,
            "mean_absolute_invoice_discrepancy": invoice_discrepancy,
        },
        "fallback": "conservative_generic_prior" if blockers else None,
        "promotion_blockers": blockers,
    }
    result["digest"] = _digest(result)
    return result


__all__ = ["build_resource_profile", "calibrate_workflow_effort"]
