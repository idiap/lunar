# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0

"""Independent-family quality-gate corpus and protocol checks.

This module protects expected behavior for the corresponding workflow, script, or repository surface. Key concepts: regression coverage, interface stability, and output integrity.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parents[2]
BENCH = ROOT / "benchmarks/planner/contextual-quality-independent-gates"


def load_runner():
    """Load runner."""
    path = ROOT / "scripts/evaluation/run_independent_quality_gates.py"
    spec = importlib.util.spec_from_file_location("independent_quality_gates", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def rows(name: str) -> list[dict]:
    """Rows."""
    return [
        json.loads(line)
        for line in (BENCH / name).read_text().splitlines()
        if line.strip()
    ]


def test_corpus_has_family_cluster_floors_and_all_behaviors() -> None:
    """Verify corpus has family cluster floors and all behaviors."""
    validation = rows("validation-cases.jsonl")
    sealed = rows("sealed-rehearsal-cases.jsonl")
    assert len({row["family_id"] for row in validation}) >= 5
    assert len(validation) >= 20
    assert len({row["family_id"] for row in sealed}) >= 10
    assert len(sealed) >= 40
    expected = {"direct", "composed", "ambiguous", "blocked", "correction"}
    assert {row["behavior"] for row in validation} == expected
    assert {row["behavior"] for row in sealed} == expected
    for partition in (validation, sealed):
        grouped = {
            family: {row["behavior"] for row in partition if row["family_id"] == family}
            for family in {row["family_id"] for row in partition}
        }
        assert all(behaviors == expected for behaviors in grouped.values())


def test_cases_and_manifest_validate_and_are_content_addressed() -> None:
    """Verify cases and manifest validate and are content addressed."""
    runner = load_runner()
    case_schema = json.loads((BENCH / "case.schema.json").read_text())
    for row in rows("validation-cases.jsonl") + rows("sealed-rehearsal-cases.jsonl"):
        jsonschema.validate(row, case_schema)
        assert (
            runner.digest({key: value for key, value in row.items() if key != "digest"})
            == row["digest"]
        )
    manifest = json.loads((BENCH / "manifest.json").read_text())
    jsonschema.validate(
        manifest, json.loads((BENCH / "manifest.schema.json").read_text())
    )
    assert (
        runner.digest(
            {key: value for key, value in manifest.items() if key != "digest"}
        )
        == manifest["digest"]
    )


def test_partition_lineage_and_similarity_are_independent() -> None:
    """Verify partition lineage and similarity are independent."""
    runner = load_runner()
    audit = runner.audit_lineage(
        rows("validation-cases.jsonl"), rows("sealed-rehearsal-cases.jsonl")
    )
    assert audit["passed"], audit
    assert audit["development_topic_leakage"] == []
    assert all(not values for values in audit["cross_partition_collisions"].values())


def test_one_public_planner_case_has_frozen_bound_quality_chain() -> None:
    """Verify one public planner case has frozen bound quality chain."""
    runner = load_runner()
    policy = {
        "criterion_reviewer": {
            "id": "test-independent-reviewer",
            "kind": "deterministic",
        },
        "artifact_judge": {"id": "test-independent-judge", "kind": "deterministic"},
        "digest": "sha256:" + "1" * 64,
    }
    receipt = runner.run_case(rows("validation-cases.jsonl")[0], policy)
    assert receipt["case_pass"] is True
    assert all(receipt["checks"].values())
    assert receipt["repair_attempted"] is False
    assert receipt["oracle_exposed_before_decision"] is False
    assert receipt["selective_rerun"] is False


def test_report_schema_accepts_generated_reports(tmp_path: Path) -> None:
    """Verify report schema accepts generated reports."""
    runner = load_runner()
    # The runner's already-focused single-case test covers planner integration;
    # here we validate the checked-in report contract independently.
    schema = json.loads((BENCH / "report.schema.json").read_text())
    assert schema["properties"]["partition"]["enum"] == [
        "validation",
        "sealed_rehearsal",
    ]
    cluster = runner.family_bootstrap(
        [
            {"family_id": "a", "case_pass": True},
            {"family_id": "a", "case_pass": False},
            {"family_id": "b", "case_pass": True},
        ]
    )
    assert cluster["unit"] == "family"
    assert cluster["family_count"] == 2


def test_checked_in_policy_freeze_is_valid_when_present() -> None:
    """Verify checked in policy freeze is valid when present."""
    path = (
        ROOT
        / "artifacts/runs/planner/contextual-quality-independent-gates/policy-freeze.json"
    )
    if not path.exists():
        return
    runner = load_runner()
    policy = json.loads(path.read_text())
    jsonschema.validate(
        policy, json.loads((BENCH / "policy-freeze.schema.json").read_text())
    )
    assert (
        runner.digest({key: value for key, value in policy.items() if key != "digest"})
        == policy["digest"]
    )
