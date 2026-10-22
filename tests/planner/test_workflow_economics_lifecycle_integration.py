# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0

"""Tests for Workflow economics lifecycle integration.

This module protects expected behavior for the corresponding workflow, script, or repository surface. Key concepts: regression coverage, interface stability, and output integrity.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from lunar_planner.contracts import seal_quality_contract, validate_contract
from lunar_planner.entrypoint import run_planner_request_with_test_surface
from lunar_planner.quality_authorization import (
    assess_authorized_workflow_economics,
    issue_workflow_economics_authorization,
    persist_authorized_workflow_economics,
)
from lunar_planner.staged_routing import (
    freeze_quality_plan,
    plan_stages,
    review_quality_plan,
)
from lunar_planner.usage_accounting import normalize_provider_usage
from lunar_planner.workflow_economics import resolve_workflow_economics_rollout
from tests.planner.quality_test_support import authorize_test_plan_review

ROOT = Path(__file__).resolve().parents[2]
KEY = b"workflow-economics-test-key-0000000000000000"


def _skill() -> dict:
    """Skill."""
    return {
        "id": "scientific:evidence-synthesis",
        "name": "evidence-synthesis",
        "scope": "scientific",
        "description": "Plan a rigorous literature synthesis with evidence review",
        "source_path": "catalog/evidence-synthesis/SKILL.md",
        "available": True,
        "invocation_posture": "instruction_only",
        "content_digest": "sha256:" + "0" * 64,
        "aliases": [],
        "purpose": {},
        "triggers": {},
        "non_triggers": {},
        "non_goals": {},
        "interface": {"inputs": {"status": "unknown", "items": []}},
        "authority": {},
    }


SURFACE = {
    "schema_version": "lunar.planner.surface-index/v1",
    "skills": [_skill()],
    "workflow_packages": [],
    "subworkflows": [],
}


def _freeze(plan: dict) -> tuple[dict, dict, dict]:
    """Freeze."""
    plan = json.loads(json.dumps(plan))
    for criterion in plan["criteria"]:
        if criterion["observable"].startswith("The artifact must expose"):
            criterion["observable"] = (
                "The artifact visibly covers every named operation, entity, qualifier, "
                "and evidence boundary in the exact active requirement."
            )
            criterion["required_anchors"] = [
                "active requirement",
                "candidate artifact",
                "evidence boundary",
            ]
    plan = seal_quality_contract(plan)
    review = review_quality_plan(
        plan, reviewer={"id": "economics-independent-reviewer"}, independent=True
    )
    assert review["verdict"] == "pass", review
    return (
        freeze_quality_plan(plan, review),
        review,
        authorize_test_plan_review(plan, review, "economics-test"),
    )


def _reach_final(**final_kwargs) -> dict:
    """Reach final."""
    first = run_planner_request_with_test_surface(
        "Plan a rigorous literature synthesis with evidence review", SURFACE
    )["planner_receipt"]
    outcome, review, authorization = _freeze(first["outcome_quality_contract"])
    second = run_planner_request_with_test_surface(
        "Resume after independent outcome-quality review.",
        SURFACE,
        continuation=first["continuation"],
        supplied_inputs={
            "frozen_outcome_quality_contract": outcome,
            "outcome_quality_review": review,
            "authorized_outcome_quality_review": authorization,
        },
    )["planner_receipt"]
    delivery, delivery_review, delivery_authorization = _freeze(
        second["delivery_quality_plan"]
    )
    return run_planner_request_with_test_surface(
        "Resume after independent delivery-quality review.",
        SURFACE,
        continuation=second["continuation"],
        supplied_inputs={
            "frozen_delivery_quality_plan": delivery,
            "delivery_quality_review": delivery_review,
            "authorized_delivery_quality_review": delivery_authorization,
        },
        **final_kwargs,
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


def _workload() -> dict:
    """Workload."""
    return {
        "work_units": [
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
    }


def test_default_off_is_exactly_compatible_and_opt_in_is_additive() -> None:
    """Verify default off is exactly compatible and opt in is additive."""
    assert (
        inspect.signature(plan_stages).parameters["workflow_economics_enabled"].default
        is False
    )
    plain = run_planner_request_with_test_surface(
        "Plan a rigorous literature synthesis with evidence review", SURFACE
    )
    explicit_off = run_planner_request_with_test_surface(
        "Plan a rigorous literature synthesis with evidence review",
        SURFACE,
        workflow_economics_enabled=False,
        workflow_economics_mode="off",
        workflow_economics_rollout_state="off",
    )
    assert plain == explicit_off

    result = _reach_final(
        workflow_economics_enabled=True,
        workflow_economics_mode="estimate",
        workflow_economics_rollout_state="fixture",
        workflow_economics_comparator=_comparator(),
        workflow_economics_workload_manifest=_workload(),
    )
    assert result["workflow_effort_estimate"]["status"] == "estimated"
    assert result["workflow_economics_report"]["scientific_release_effect"] is False
    assert result["planner_receipt"]["selected_targets"] == result["selected_targets"]
    for name in (
        "workflow_workload_inventory",
        "workflow_effort_estimate",
        "workflow_resource_estimate",
        "workflow_economics_report",
    ):
        assert validate_contract(result[name]).valid, validate_contract(
            result[name]
        ).errors


def test_advisory_promotion_fails_closed_until_all_metrics_pass() -> None:
    """Verify advisory promotion fails closed until all metrics pass."""
    blocked = resolve_workflow_economics_rollout("advisory")
    assert blocked["effective_state"] == "audit"
    assert blocked["promotion_blockers"]
    policy = json.loads(
        (
            ROOT
            / "app/backend/lunar_planner/resources/policies/workflow-economics-policy-v1.json"
        ).read_text()
    )
    gates = policy["promotion_gates"]
    metrics = {
        "effort_interval_coverage": gates["minimum_effort_interval_coverage"],
        "complete_fixture_arithmetic_replay_rate": gates[
            "complete_fixture_arithmetic_replay_rate"
        ],
        "human_reviewers": gates["minimum_human_reviewers"],
        "false_complete_rate": gates["maximum_false_complete_rate"],
        "false_positive_savings_rate": gates["maximum_false_positive_savings_rate"],
        "planned_as_observed_escape_count": gates["planned_as_observed_escape_count"],
        "budget_as_usage_escape_count": gates["budget_as_usage_escape_count"],
        "missing_as_zero_escape_count": gates["missing_as_zero_escape_count"],
        "legacy_compatibility_failure_count": gates[
            "legacy_compatibility_failure_count"
        ],
        "p95_latency_ms": gates["maximum_p95_latency_ms"],
        "mean_artifact_bytes": gates["maximum_mean_artifact_bytes"],
    }
    assert (
        resolve_workflow_economics_rollout("advisory", promotion_metrics=metrics)[
            "effective_state"
        ]
        == "advisory"
    )

    with pytest.raises(ValueError, match="explicit authorized host APIs"):
        run_planner_request_with_test_surface(
            "Plan a rigorous literature synthesis with evidence review",
            SURFACE,
            workflow_economics_mode="observe",
        )


def test_authorized_observation_is_tamper_evident_and_persists_only_via_port() -> None:
    """Verify authorized observation is tamper evident and persists only via port."""
    result = _reach_final(
        workflow_economics_enabled=True,
        workflow_economics_mode="estimate",
        workflow_economics_rollout_state="fixture",
        workflow_economics_comparator=_comparator(),
        workflow_economics_workload_manifest=_workload(),
    )
    effort, resource = (
        result["workflow_effort_estimate"],
        result["workflow_resource_estimate"],
    )
    receipt = normalize_provider_usage(
        {
            "workflow_id": "wf",
            "component_id": "read",
            "attempt_id": "a1",
            "provider": "provider",
            "model": "model",
            "timestamp": "2026-08-01T00:00:00Z",
            "usage": {"input_tokens": 100, "output_tokens": 0},
        },
        {},
    )
    priced = {
        "currency": "USD",
        "price_book_digest": "sha256:" + "5" * 64,
        "priced_lines": [{"cost_nano": 200, "resource_class": "input_tokens"}],
        "unpriced_lines": [],
        "priced_total_nano": 200,
        "line_coverage": {"priced": 1, "unpriced": 0, "total": 1},
        "complete": True,
    }
    authorization = issue_workflow_economics_authorization(
        effort,
        resource,
        [receipt],
        plan_digest=resource["plan_digest"],
        comparator_digest="sha256:" + "6" * 64,
        workload_inventory_digest=result["workflow_workload_inventory"]["digest"],
        price_book_digest=priced["price_book_digest"],
        nonce="n1",
        trusted_key=KEY,
    )
    package = assess_authorized_workflow_economics(
        effort,
        resource,
        [receipt],
        priced,
        authorization=authorization,
        trusted_key=KEY,
    )

    class Store:
        """Initialize store."""

        """Represent store."""

        def __init__(self):
            self.rows = []

        def write(self, logical_id: str, payload: bytes):
            """Write."""
            self.rows.append((logical_id, payload))
            return {"logical_id": logical_id, "size": len(payload)}

    store = Store()
    persisted = persist_authorized_workflow_economics(
        package, plan_id="plan-1", artifact_store=store, trusted_key=KEY
    )
    assert persisted["logical_id"].startswith(
        "artifacts/runs/planner/plan-1/workflow-economics/"
    )
    with pytest.raises(ValueError, match="changed after authorization"):
        assess_authorized_workflow_economics(
            effort,
            {**resource, "seed": 99},
            [receipt],
            priced,
            authorization=authorization,
            trusted_key=KEY,
        )


def test_development_benchmark_has_declared_threat_coverage() -> None:
    """Verify development benchmark has declared threat coverage."""
    root = ROOT / "benchmarks/planner/workflow-economics"
    manifest = json.loads((root / "manifest.json").read_text())
    cases = [
        json.loads(line)
        for line in (root / "cases.jsonl").read_text().splitlines()
        if line.strip()
    ]
    assert len(cases) == manifest["case_count"] >= 15
    threat_map = manifest["category_threat_map"]
    covered = {
        threat
        for case in cases
        for threat in threat_map.get(str(case.get("category")), ())
    }
    assert set(manifest["required_threats"]) <= covered
    assert manifest["promotion_evidence"] is False
