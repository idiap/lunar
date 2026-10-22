# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0

"""Tests for Workflow economics contracts.

This module protects expected behavior for the corresponding workflow, script, or repository surface. Key concepts: regression coverage, interface stability, and output integrity.
"""

from __future__ import annotations

from copy import deepcopy

from lunar_planner.contracts import validate_contract
from lunar_planner.pricing import price_usage_lines, seal_price_book
from lunar_planner.usage_accounting import (
    estimate_workflow_resources,
    normalize_provider_usage,
)
from lunar_planner.workflow_economics import (
    build_workflow_cost_reconciliation,
    build_workflow_economics_report,
    build_workflow_effort_card,
    build_workflow_resource_usage,
    compile_work_units,
    estimate_workflow_effort,
    invalidate_workflow_effort,
    validate_comparator_equivalence,
)


def _comparator() -> dict:
    """Comparator."""
    return {
        "workflow_digest": "sha256:" + "1" * 64,
        "workload_manifest_digest": "sha256:" + "2" * 64,
        "scope": True,
        "rigor": True,
        "evidence_coverage": True,
        "provenance": True,
        "reproducibility": True,
        "acceptance_tests": True,
        "review_posture": True,
        "practitioner": "experienced_practitioner",
        "ordinary_non_agentic_tools": ["browser", "spreadsheet"],
    }


def _units() -> list[dict]:
    """Units."""
    return [
        {
            "work_unit_id": "read",
            "stage_id": "evidence",
            "activity_class": "reading_interpretation",
            "quantity": 10,
            "quantity_unit": "paper",
            "output_artifact_ids": ["notes"],
            "manual": {"rate_hours_per_unit": 0.5},
            "assisted": {"human_setup_hours": 0.2, "mandatory_review_hours": 1},
            "resource_drivers": [
                {
                    "resource_class": "input_tokens",
                    "unit": "token",
                    "p10": 100,
                    "p50": 200,
                    "p90": 300,
                }
            ],
        }
    ]


def _price_book() -> dict:
    """Price book."""
    return seal_price_book(
        {
            "schema_version": "lunar.planner.price-book/v1",
            "retrieved_at": "2026-08-01T00:00:00Z",
            "rates": [
                {
                    "provider": "provider",
                    "service": "model",
                    "region": "global",
                    "tier": "standard",
                    "resource_class": "input_tokens",
                    "unit": "token",
                    "currency": "USD",
                    "effective_from": "2026-01-01T00:00:00Z",
                    "effective_to": "2027-01-01T00:00:00Z",
                    "rate_nano": 2_000_000_000,
                    "rate_unit": 1_000_000,
                    "rounding": "half_even",
                    "authority": "provider_published",
                }
            ],
        }
    )


def test_every_planner_economics_artifact_passes_strict_contracts() -> None:
    """Verify every planner economics artifact passes strict contracts."""
    comparator = validate_comparator_equivalence(_comparator())
    inventory = compile_work_units(
        {"stages": [{"id": "evidence", "work_units": _units()}]}
    )
    effort = estimate_workflow_effort(_comparator(), inventory, samples=100)
    resource = estimate_workflow_resources(
        {"name": "workflow"}, inventory["work_units"]
    )
    artifacts = [
        comparator,
        inventory,
        effort,
        resource,
        build_workflow_effort_card(effort),
        invalidate_workflow_effort(
            effort, ["sha256:" + "3" * 64], affected_work_unit_ids=["read"]
        ),
        build_workflow_economics_report(effort, resource),
        _price_book(),
    ]
    for artifact in artifacts:
        report = validate_contract(artifact)
        assert report.valid, (artifact["schema_version"], report.errors)


def test_observed_usage_cost_and_unpriced_polarity_are_replayable() -> None:
    """Verify observed usage cost and unpriced polarity are replayable."""
    normalized = normalize_provider_usage(
        {
            "workflow_id": "wf",
            "component_id": "read",
            "attempt_id": "attempt-1",
            "provider": "provider",
            "model": "model",
            "timestamp": "2026-08-01T00:00:00Z",
            "usage": {"input_tokens": 100, "output_tokens": 0},
        },
        {},
    )
    usage = build_workflow_resource_usage("sha256:" + "4" * 64, [normalized])
    priced = price_usage_lines(
        [
            {
                "provider": "provider",
                "service": "model",
                "region": "global",
                "tier": "standard",
                "resource_class": "input_tokens",
                "unit": "token",
                "quantity": 100,
                "timestamp": "2026-08-01T00:00:00Z",
                "evidence_state": "provider_observed",
            }
        ],
        _price_book(),
        currency="USD",
    )
    cost = build_workflow_cost_reconciliation(usage, priced)
    assert validate_contract(usage).valid, validate_contract(usage).errors
    assert validate_contract(cost).valid, validate_contract(cost).errors

    unpriced = deepcopy(cost)
    unpriced["missing_price_as_zero"] = True
    assert (
        "missing prices cannot be represented as zero cost"
        in validate_contract(unpriced).errors
    )

    partial_pricing = {
        **priced,
        "complete": False,
        "priced_lines": [],
        "unpriced_lines": [{"cost_state": "not_calculable"}],
        "priced_total_nano": 0,
        "line_coverage": {"priced": 0, "unpriced": 1, "total": 1},
    }
    partial_cost = build_workflow_cost_reconciliation(usage, partial_pricing)
    effort = estimate_workflow_effort(_comparator(), _units(), samples=100)
    assert (
        build_workflow_economics_report(effort, usage, cost=partial_cost)["status"]
        == "partial"
    )


def test_semantic_tampering_and_planned_as_observed_are_rejected() -> None:
    """Verify semantic tampering and planned as observed are rejected."""
    effort = estimate_workflow_effort(_comparator(), _units(), samples=100)
    tampered = deepcopy(effort)
    tampered["headline"]["net_saved_person_hours"]["p50"] += 1
    errors = validate_contract(tampered).errors
    assert "net saved p50 does not equal manual p50 minus assisted p50" in errors
    assert "digest does not match canonical document content" in errors

    wrong_polarity = deepcopy(effort)
    wrong_polarity["evidence_state"] = "observed"
    assert any(
        "prospective evidence polarity" in row
        for row in validate_contract(wrong_polarity).errors
    )
