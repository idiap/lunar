# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0

"""Prospective/observed reconciliation and invalidation tests.

This module protects expected behavior for the corresponding workflow, script, or repository surface. Key concepts: regression coverage, interface stability, and output integrity.
"""

from __future__ import annotations

from lunar_planner.provenance import (
    build_invalidation_report,
    export_w3c_provenance,
    propagate_invalidation,
    reconcile_components,
)
from lunar_planner.contracts import require_valid_contract


def test_planned_never_masquerades_as_observed() -> None:
    """Verify planned never masquerades as observed."""
    report = reconcile_components(
        [{"component_id": "claim-1", "producer": "skill-a", "release_critical": True}],
        [],
    )
    row = report["components"][0]
    assert row["prospective_status"] == "planned"
    assert row["observed_status"] == "missing"
    assert row["reconciliation_status"] == "missing_observation"
    assert row["release_blocking"] is True
    assert report["summary"]["complete"] is False

    not_run = reconcile_components(
        [{"component_id": "claim-1"}],
        [{"component_id": "claim-1", "status": "not_executed"}],
    )["components"][0]
    assert not_run["observed_status"] == "not_executed"
    assert not_run["reconciliation_status"] == "not_executed"


def test_matching_unplanned_and_digest_mismatch_are_explicit() -> None:
    """Verify matching unplanned and digest mismatch are explicit."""
    report = reconcile_components(
        [
            {"component_id": "a", "expected_digest": "sha256:1"},
            {"component_id": "b", "expected_digest": "sha256:2"},
        ],
        [
            {"component_id": "a", "digest": "sha256:1"},
            {"component_id": "b", "digest": "sha256:wrong"},
            {"component_id": "c", "digest": "sha256:3"},
        ],
    )
    statuses = {
        row["component_id"]: row["reconciliation_status"]
        for row in report["components"]
    }
    assert statuses == {
        "a": "matched",
        "b": "digest_mismatch",
        "c": "unexpected_observation",
    }
    assert report["summary"]["release_blocking"] is True


def test_redacted_and_private_observations_are_explicit_omissions() -> None:
    """Verify redacted and private observations are explicit omissions."""
    report = reconcile_components(
        [{"component_id": "a"}, {"component_id": "b"}],
        [
            {"component_id": "a", "status": "redacted", "secret": "hidden"},
            {
                "component_id": "b",
                "privacy_class": "restricted",
                "raw_prompt": "hidden",
            },
        ],
    )
    assert [row["observed_status"] for row in report["components"]] == [
        "redacted",
        "redacted",
    ]
    assert all(row["observed"]["status"] == "redacted" for row in report["components"])
    assert "hidden" not in str(report)
    assert report["boundary"]["prospective_is_observation"] is False


def test_invalidation_is_transitive_cycle_safe_and_deterministic() -> None:
    """Verify invalidation is transitive cycle safe and deterministic."""
    first = propagate_invalidation(
        {"source": ["b", "a"], "a": ["release"], "b": ["release"], "release": ["a"]},
        ["source"],
    )
    second = propagate_invalidation(
        {"release": ["a"], "b": ["release"], "a": ["release"], "source": ["a", "b"]},
        ["source"],
    )
    assert first == second == ["source", "a", "b", "release"]
    report = build_invalidation_report(
        {"input": ["plan"], "plan": ["acceptance"]}, ["input"], reason="digest changed"
    )
    assert report["invalidated_ids"] == ["input", "plan", "acceptance"]
    assert report["invalidation_digest"].startswith("sha256:")


def _planner_result() -> dict[str, object]:
    """Planner result."""
    return {
        "schema_version": "lunar.planner.routing-decision/v1",
        "command_text": "Assess BRAF actionability in melanoma",
        "mode": "new_workflow",
        "status": "needs_quality_review",
        "route_only": True,
        "performed_actions": [],
        "workflow_draft": {
            "status": "prospective",
            "stages": [{"component_id": "civic-reader"}],
        },
        "planner_receipt": {
            "digest": "sha256:" + "1" * 64,
            "raw_prompt": "must not be exported",
        },
    }


def test_w3c_prov_json_export_is_deterministic_and_privacy_safe() -> None:
    """Verify w3c prov JSON export is deterministic and privacy safe."""
    first = export_w3c_provenance(_planner_result())
    second = export_w3c_provenance(_planner_result(), output_format="w3c-prov-json")

    assert first == second
    assert first["format"] == "prov-json"
    assert first["standard"] == "W3C PROV"
    assert first["prospective_is_observation"] is False
    assert first["document"]["prefix"]["prov"] == "http://www.w3.org/ns/prov#"
    assert len(first["document"]["activity"]) == 1
    assert len(first["document"]["agent"]) == 1
    assert "must not be exported" not in str(first)
    assert "privacy_boundary" in str(first)
    require_valid_contract(first)


def test_w3c_export_keeps_plans_as_entities_and_observations_explicit() -> None:
    """Verify w3c export keeps plans as entities and observations explicit."""
    reconciliation = reconcile_components(
        [
            {"component_id": "planned-only", "release_critical": False},
            {"component_id": "executed", "release_critical": True},
        ],
        [{"component_id": "executed", "status": "observed", "digest": "sha256:1"}],
    )
    exported = export_w3c_provenance(
        _planner_result(), reconciliation=reconciliation, output_format="json-ld"
    )

    assert exported["format"] == "json-ld"
    graph = exported["document"]["@graph"]
    activities = [row for row in graph if row["@type"] == "prov:Activity"]
    prospective = [
        row for row in graph if row.get("prov:type") == "lunar:ProspectiveComponent"
    ]
    observed = [
        row
        for row in graph
        if row.get("prov:type") == "lunar:RetrospectiveComponentObservation"
    ]
    assert len(activities) == 1
    assert len(prospective) == 2
    assert len(observed) == 1
    assert observed[0]["prov:specializationOf"]
    require_valid_contract(exported)


def test_w3c_export_rejects_unknown_format_and_noncanonical_reconciliation() -> None:
    """Verify w3c export rejects unknown format and noncanonical reconciliation."""
    import pytest

    with pytest.raises(ValueError, match="output_format"):
        export_w3c_provenance(_planner_result(), output_format="rdf-xml")
    with pytest.raises(ValueError, match="reconciliation"):
        export_w3c_provenance(_planner_result(), reconciliation={})
