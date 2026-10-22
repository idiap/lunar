# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0

"""Tests for Workflow economics effort.

This module protects expected behavior for the corresponding workflow, script, or repository surface. Key concepts: regression coverage, interface stability, and output integrity.
"""

from __future__ import annotations

from copy import deepcopy

import pytest

from lunar_planner.workflow_economics import (
    WorkflowEconomicsError,
    build_workflow_effort_card,
    compile_work_units,
    estimate_workflow_effort,
    invalidate_workflow_effort,
    validate_comparator_equivalence,
)


def comparator(**overrides):
    """Comparator."""
    value = {
        "workflow_digest": "sha256:workflow",
        "workload_manifest_digest": "sha256:manifest",
        "scope": True,
        "rigor": True,
        "evidence_coverage": True,
        "provenance": True,
        "reproducibility": True,
        "acceptance_tests": True,
        "review_posture": True,
        "practitioner": "experienced_practitioner",
        "ordinary_non_agentic_tools": ["search portal", "spreadsheet"],
    }
    value.update(overrides)
    return value


def units(assisted_review=1.0):
    """Units."""
    return [
        {
            "work_unit_id": "screen",
            "stage_id": "evidence",
            "activity_class": "screening_selection",
            "quantity": {"low": 90, "mode": 100, "high": 120},
            "quantity_unit": "candidate records",
            "output_artifact_ids": ["selected"],
            "manual": {"rate_hours_per_unit": 0.05, "setup_hours": 0.5},
            "assisted": {
                "human_setup_hours": 0.25,
                "mandatory_review_hours": assisted_review,
            },
            "human_waiting_hours": 0.2,
            "machine_runtime_hours": 0.1,
            "correlation_group": "source_count",
            "evidence_grade": "matched_benchmark",
        },
        {
            "work_unit_id": "read",
            "stage_id": "evidence",
            "activity_class": "reading_interpretation",
            "quantity": {"low": 9, "mode": 10, "high": 12},
            "quantity_unit": "full texts",
            "output_artifact_ids": ["notes"],
            "dependencies": ["screen"],
            "manual": {
                "rate_hours_per_unit": {"low": 0.4, "mode": 0.5, "high": 0.7},
                "complexity": 1.2,
                "expected_rework_hours": 0.2,
            },
            "assisted": {
                "work_not_automated_hours": 0.5,
                "mandatory_review_hours": 2,
                "new_assurance_hours": 0.5,
                "defect_probability": 0.2,
                "correction_effort_hours": 1,
            },
            "one_time_setup_hours": 4,
            "machine_runtime_hours": 0.4,
            "correlation_group": "source_count",
            "evidence_grade": "expert_prior",
        },
    ]


def test_comparator_requires_output_equivalence():
    """Verify comparator requires output equivalence."""
    assert validate_comparator_equivalence(comparator())["status"] == "equivalent"
    result = validate_comparator_equivalence(comparator(rigor=False))
    assert result["status"] == "not_equivalent"
    assert "rigor" in result["mismatched_dimensions"]


def test_compiler_is_non_mutating_deterministic_and_detects_double_credit():
    """Verify compiler is non mutating deterministic and detects double credit."""
    plan = {"digest": "sha256:p", "stages": [{"id": "evidence", "work_units": units()}]}
    before = deepcopy(plan)
    first = compile_work_units(plan)
    second = compile_work_units(plan)
    assert plan == before
    assert first == second
    assert first["estimable"] is True
    duplicate = deepcopy(units()[0])
    duplicate["work_unit_id"] = "screen-again"
    result = compile_work_units(
        {"stages": [{"id": "evidence", "work_units": units() + [duplicate]}]}
    )
    assert not result["estimable"]
    assert result["duplicate_operations"]


def test_compiler_does_not_invent_missing_quantities():
    """Verify compiler does not invent missing quantities."""
    result = compile_work_units(
        {
            "stages": [
                {
                    "id": "s",
                    "work_units": [
                        {
                            "activity_class": "reading_interpretation",
                            "output_artifact_ids": ["o"],
                        }
                    ],
                }
            ]
        }
    )
    assert not result["estimable"]
    assert {row["driver"] for row in result["unresolved_drivers"]} >= {
        "quantity",
        "quantity_unit",
    }


def test_seeded_estimation_reconciles_and_preserves_four_clocks():
    """Verify seeded estimation reconciles and preserves four clocks."""
    first = estimate_workflow_effort(comparator(), units(), seed=7, samples=500)
    second = estimate_workflow_effort(
        comparator(), list(reversed(units())), seed=7, samples=500
    )
    assert first == second
    headline = first["headline"]
    assert headline["net_saved_person_hours"]["p50"] == pytest.approx(
        headline["manual_person_hours"]["p50"]
        - headline["assisted_person_hours"]["p50"]
    )
    assert first["clocks"]["machine_runtime_hours"] != headline["assisted_person_hours"]
    assert (
        first["clocks"]["calendar_critical_path_hours"]["manual"]["p50"]
        <= headline["manual_person_hours"]["p50"]
    )
    assert (
        first["sensitivity"][0]["p90_minus_p10_proxy_hours"]
        >= first["sensitivity"][1]["p90_minus_p10_proxy_hours"]
    )


def test_negative_savings_is_not_clamped():
    """Verify negative savings is not clamped."""
    result = estimate_workflow_effort(
        comparator(), units(assisted_review=20), samples=200
    )
    assert result["headline"]["negative_savings"] is True
    assert result["headline"]["net_saved_person_hours"]["p50"] < 0
    assert result["headline"]["saving_fraction_at_p50"] < 0


def test_one_time_setup_is_amortized_without_changing_marginal_work():
    """Verify one time setup is amortized without changing marginal work."""
    once = estimate_workflow_effort(comparator(), units(), repetitions=1, samples=200)
    ten = estimate_workflow_effort(comparator(), units(), repetitions=10, samples=200)
    assert (
        ten["headline"]["manual_person_hours"]["p50"]
        < once["headline"]["manual_person_hours"]["p50"]
    )
    assert all(
        row["one_time_setup_amortized_over_runs"] == 10 for row in ten["components"]
    )


def test_non_equivalent_or_unresolved_inputs_are_not_estimable():
    """Verify non equivalent or unresolved inputs are not estimable."""
    result = estimate_workflow_effort(comparator(scope=False), units(), samples=100)
    assert result["status"] == "not_estimable"
    assert result["headline"] is None
    broken = deepcopy(units())
    broken[0]["quantity"] = "unknown"
    assert (
        estimate_workflow_effort(comparator(), broken, samples=100)["status"]
        == "not_estimable"
    )


def test_observed_polarity_requires_receipts_and_cycle_fails():
    """Verify observed polarity requires receipts and cycle fails."""
    with pytest.raises(WorkflowEconomicsError, match="receipts"):
        estimate_workflow_effort(comparator(), units(), evidence_state="observed")
    cyclic = units()
    cyclic[0]["dependencies"] = ["read"]
    with pytest.raises(WorkflowEconomicsError, match="cycle"):
        estimate_workflow_effort(comparator(), cyclic, samples=100)


def test_observed_assessment_uses_digest_bound_human_effort_receipts():
    """Verify observed assessment uses digest bound human effort receipts."""
    receipts = {
        row["work_unit_id"]: {
            "evidence_state": "observed",
            "digest": f"sha256:{row['work_unit_id']}",
            "manual_person_hours": 3,
            "assisted_person_hours": 1,
            "human_waiting_hours": 0.5,
            "machine_runtime_hours": 0.25,
        }
        for row in units()
    }
    result = estimate_workflow_effort(
        comparator(),
        units(),
        evidence_state="observed",
        observed_receipts=receipts,
        samples=100,
    )
    assert result["status"] == "assessed"
    assert result["headline"]["manual_person_hours"]["p50"] == 6
    assert result["headline"]["assisted_person_hours"]["p50"] == 2
    assert {row["observed_receipt_digest"] for row in result["components"]} == {
        "sha256:screen",
        "sha256:read",
    }


def test_card_and_selective_invalidation_keep_ranges_visible():
    """Verify card and selective invalidation keep ranges visible."""
    estimate = estimate_workflow_effort(comparator(), units(), samples=100)
    card = build_workflow_effort_card(estimate)
    assert card["headline"] == estimate["headline"]
    invalidation = invalidate_workflow_effort(
        estimate, ["sha256:changed"], affected_work_unit_ids=["read"]
    )
    assert invalidation["invalidated_work_unit_ids"] == ["read"]
    assert invalidation["retained_work_unit_ids"] == ["screen"]


def test_bad_intervals_probabilities_and_nan_fail_deterministically():
    """Verify bad intervals probabilities and nan fail deterministically."""
    bad = units()
    bad[0]["quantity"] = {"low": 2, "mode": 1, "high": 3}
    assert (
        estimate_workflow_effort(comparator(), bad, samples=100)["status"]
        == "not_estimable"
    )
    bad = units()
    bad[0]["assisted"]["defect_probability"] = 2
    assert (
        estimate_workflow_effort(comparator(), bad, samples=100)["status"]
        == "not_estimable"
    )
    bad = units()
    bad[0]["quantity"] = float("nan")
    assert (
        estimate_workflow_effort(comparator(), bad, samples=100)["status"]
        == "not_estimable"
    )
