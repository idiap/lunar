# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0

"""Pure calibration metrics for answer-trust policies.

The caller supplies a frozen, blinded corpus and independent review rows. This
module does not recruit reviewers, expose sealed oracles, or tune policy values.
It reports whether the supplied evidence is sufficient for rollout promotion.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from typing import Any


def _digest(value: Any) -> str:
    """Digest."""
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _ratio(numerator: int, denominator: int) -> float | None:
    """Ratio."""
    return numerator / denominator if denominator else None


def calibrate_answer_trust(
    assessments: Sequence[Mapping[str, Any]],
    expert_reviews: Sequence[Mapping[str, Any]],
    *,
    corpus_id: str,
    corpus_digest: str,
    frozen: bool,
    blinded: bool,
    partition: str,
    minimum_reviewers_per_case: int = 2,
) -> dict[str, Any]:
    """Measure escape, false-block, interval, band, and reviewer agreement."""

    predicted = {str(row.get("case_id")): dict(row) for row in assessments}
    if len(predicted) != len(assessments) or "" in predicted:
        raise ValueError("assessment case IDs must be non-empty and unique")
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    reviewer_case_pairs: set[tuple[str, str]] = set()
    for raw in expert_reviews:
        row = dict(raw)
        case_id, reviewer_id = str(row.get("case_id", "")), str(
            row.get("reviewer_id", "")
        )
        if not case_id or not reviewer_id:
            raise ValueError("expert review requires case and reviewer identity")
        if (case_id, reviewer_id) in reviewer_case_pairs:
            raise ValueError("one reviewer may submit only one review per case")
        reviewer_case_pairs.add((case_id, reviewer_id))
        grouped[case_id].append(row)
    unknown = sorted(set(grouped) - set(predicted))
    if unknown:
        raise ValueError(f"expert reviews reference unknown cases: {unknown}")

    adjudicated: dict[str, dict[str, Any]] = {}
    disagreement_cases = 0
    for case_id in sorted(predicted):
        rows = grouped.get(case_id, [])
        dispositions = Counter(str(row.get("disposition")) for row in rows)
        if len(dispositions) > 1:
            disagreement_cases += 1
        disposition = (
            sorted(dispositions.items(), key=lambda item: (-item[1], item[0]))[0][0]
            if dispositions
            else "unreviewed"
        )
        scores = [
            float(row["reference_score"])
            for row in rows
            if row.get("reference_score") is not None
        ]
        bands = Counter(
            str(row.get("reference_band")) for row in rows if row.get("reference_band")
        )
        adjudicated[case_id] = {
            "reviewer_count": len(rows),
            "disposition": disposition,
            "reference_score": sum(scores) / len(scores) if scores else None,
            "reference_band": (
                sorted(bands.items(), key=lambda item: (-item[1], item[0]))[0][0]
                if bands
                else None
            ),
        }

    unsupported_cases = [
        case_id
        for case_id, row in adjudicated.items()
        if row["disposition"] in {"blocked", "unsupported"}
    ]
    acceptable_cases = [
        case_id
        for case_id, row in adjudicated.items()
        if row["disposition"] in {"acceptable", "substantiated", "guarded"}
    ]
    blocked_predictions = {
        case_id
        for case_id, row in predicted.items()
        if row.get("status") == "blocked" or row.get("band") == "blocked_untrusted"
    }
    true_block = len(set(unsupported_cases) & blocked_predictions)
    false_block = len(set(acceptable_cases) & blocked_predictions)

    covered, eligible_interval = 0, 0
    confusion: dict[str, Counter[str]] = defaultdict(Counter)
    for case_id, reference in adjudicated.items():
        prediction = predicted[case_id]
        interval = prediction.get("score_interval")
        score = reference["reference_score"]
        if score is not None and isinstance(interval, Sequence) and len(interval) == 2:
            eligible_interval += 1
            covered += int(float(interval[0]) <= score <= float(interval[1]))
        if reference["reference_band"]:
            confusion[reference["reference_band"]][str(prediction.get("band"))] += 1

    threat_totals = Counter(str(row.get("threat_class")) for row in predicted.values())
    threat_detected = Counter(
        str(row.get("threat_class"))
        for case_id, row in predicted.items()
        if case_id in blocked_predictions
    )
    metrics = {
        "unsupported_escape_recall": _ratio(true_block, len(unsupported_cases)),
        "false_block_rate": _ratio(false_block, len(acceptable_cases)),
        "interval_coverage": _ratio(covered, eligible_interval),
        "inter_reviewer_disagreement_rate": _ratio(disagreement_cases, len(predicted)),
        "fabricated_value_detection_rate": _ratio(
            threat_detected["fabricated_value"], threat_totals["fabricated_value"]
        ),
        "citation_lineage_mismatch_detection_rate": _ratio(
            threat_detected["citation_laundering"], threat_totals["citation_laundering"]
        ),
    }
    blockers: list[str] = []
    if not frozen:
        blockers.append("calibration corpus is not frozen")
    if not blinded:
        blockers.append("expert review was not blinded")
    if partition == "release_candidate":
        blockers.append("policy calibration on release candidates is forbidden")
    insufficient = sorted(
        case_id
        for case_id, row in adjudicated.items()
        if row["reviewer_count"] < minimum_reviewers_per_case
    )
    if insufficient:
        blockers.append(f"insufficient independent reviewers for cases: {insufficient}")

    result = {
        "schema_version": "lunar.planner.answer-trust-calibration/v1",
        "corpus_id": str(corpus_id),
        "corpus_digest": str(corpus_digest),
        "partition": str(partition),
        "frozen": bool(frozen),
        "blinded": bool(blinded),
        "assessment_count": len(predicted),
        "review_count": len(expert_reviews),
        "minimum_reviewers_per_case": minimum_reviewers_per_case,
        "metrics": metrics,
        "band_confusion_matrix": {
            expected: dict(sorted(actual.items()))
            for expected, actual in sorted(confusion.items())
        },
        "adjudication": adjudicated,
        "promotion_blockers": blockers,
        "status": "calibrated" if not blockers else "insufficient_calibration_evidence",
        "policy_tuned_on_release_candidates": False,
    }
    result["digest"] = _digest(result)
    return result


__all__ = ["calibrate_answer_trust"]
