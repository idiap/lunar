# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Retained dialogue trace grader using explicit frozen domain metadata only."""

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping
from lunar_planner.entrypoint import run_planner_request_with_test_surface

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures/dialogue-workflow-evolution"


def run_planner_request(text, **kwargs):
    """Supply an explicit test-only snapshot; production has no domain default."""
    return run_planner_request_with_test_surface(
        text, json.loads((FIXTURES / "surface.json").read_text()), **kwargs
    )


def digest(value: Any) -> str:
    """Digest."""
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(raw.encode()).hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Read jsonl."""
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def load_public(
    manifest_path: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]], Path]:
    """Load public."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != "bioagents.planner.dialogue-benchmark/v1":
        raise ValueError("unsupported dialogue benchmark manifest")
    cases = read_jsonl(manifest_path.parent / manifest["public_cases"]["path"])
    if digest(cases) != manifest["public_cases"]["digest"]:
        raise ValueError("public dialogue corpus digest mismatch")
    if len(cases) != 20 or sum(row.get("turn_count", 0) for row in cases) != 100:
        raise ValueError("benchmark requires 20 dialogues and 100 user turns")
    for case in cases:
        if len(case.get("turns", ())) != 5:
            raise ValueError(f"{case.get('case_id')} must have five turns")
        forbidden = {"acceptable_component_groups", "content_criteria", "oracle"}
        if forbidden & set(case):
            raise ValueError(f"public case leaks oracle fields: {case['case_id']}")
    return manifest, cases, manifest_path.parent / manifest["private_oracles"]["path"]


def authority_and_inputs(
    turn: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Authority and inputs."""
    values = dict(turn.get("supplied_inputs", {}))
    authority: dict[str, Any] = {}
    if "denied_permissions" in values:
        authority["denied_permissions"] = values.pop("denied_permissions")
    return authority, values


def compact_receipt(receipt: Mapping[str, Any]) -> dict[str, Any]:
    """Compact receipt."""
    state = receipt.get("dialogue_state", {})
    instantiation = receipt.get("workflow_instantiation", {})
    cycle = receipt.get("workflow_refinement_cycle", {})
    return {
        "turn_index": state.get("turn_index"),
        "disposition": receipt.get("disposition"),
        "planning_phase": state.get("planning_phase"),
        "active_inputs": state.get("active_inputs", {}),
        "requirements": [
            {
                "id": row.get("requirement_id"),
                "status": row.get("status"),
                "text": row.get("active_text", row.get("text")),
            }
            for row in receipt.get("requirement_ledger", {}).get("requirements", ())
        ],
        "components": [
            (node.get("component") or {}).get("id") or node.get("gap_id")
            for node in instantiation.get("nodes", ())
        ],
        "nodes": [
            {
                "node_id": node.get("node_id"),
                "requirement_id": node.get("requirement_id"),
                "requirement_ids": node.get(
                    "requirement_ids", [node.get("requirement_id")]
                ),
                "implementation_kind": node.get("implementation_kind"),
                "component": (node.get("component") or {}).get("id"),
                "gap_id": node.get("gap_id"),
                "status": node.get("status"),
                "composed_requirement_ids": node.get("composed_requirement_ids", []),
            }
            for node in instantiation.get("nodes", ())
        ],
        "edges": instantiation.get("edges", []),
        "blockers": instantiation.get("blockers", []),
        "terminal_artifact": instantiation.get("terminal_artifact"),
        "gap_classes": [
            gap.get("proposed_component_class")
            for gap in (receipt.get("capability_gap_plan") or {}).get("gaps", ())
        ],
        "proposed_skill_test_plan_count": len(
            receipt.get("proposed_skill_test_plans", ())
        ),
        "refinement": {
            "status": cycle.get("status"),
            "diagnostic": cycle.get("diagnostic"),
            "fix_plan": cycle.get("fix_plan"),
            "release_gate": cycle.get("release_gate"),
            "findings": cycle.get("findings", []),
            "workflow_test_specifications": cycle.get(
                "workflow_test_specifications", []
            ),
            "required_test_ids": cycle.get("required_test_ids", []),
            "verified_test_ids": cycle.get("verified_test_ids", []),
            "missing_execution_test_ids": cycle.get("missing_execution_test_ids", []),
        },
    }


def run_case(case: Mapping[str, Any]) -> dict[str, Any]:
    """Run case."""
    from lunar_planner.benchmark_quality import (
        drive_route_only_quality_protocol,
    )

    continuation = None
    turns: list[dict[str, Any]] = []
    for index, turn in enumerate(case["turns"], 1):
        authority, inputs = authority_and_inputs(turn)
        result = run_planner_request(
            str(turn["utterance"]),
            supplied_inputs=inputs,
            authority_envelope=authority,
            continuation=continuation,
        )
        # The production planner now has two mandatory quality freezes before
        # retrieval and workflow instantiation.  Dialogue benchmarking drives
        # those freezes through the explicit benchmark-only adapter so each
        # expert utterance still yields a fully instantiated route receipt.
        # This certifies state-machine conformance only; it does not claim
        # biomedical artifact quality or authorize execution.
        result = drive_route_only_quality_protocol(
            result,
            call_planner=lambda text, **values: run_planner_request(
                text,
                authority_envelope=authority,
                **values,
            ),
        )
        receipt = result.get("planner_receipt")
        if not isinstance(receipt, Mapping):
            turns.append(
                {
                    "turn_index": index,
                    "utterance": turn["utterance"],
                    "error": "planner returned no staged receipt",
                    "result": result,
                }
            )
            break
        turns.append(
            {
                "turn_index": index,
                "utterance": turn["utterance"],
                "supplied_inputs": inputs,
                "authority": authority,
                "result_mode": result.get("mode"),
                "receipt_digest": receipt.get("digest"),
                "receipt": receipt,
            }
        )
        continuation = receipt.get("continuation")
    sealed = {
        "case_id": case["case_id"],
        "family_id": case["family_id"],
        "variant": case["variant"],
        "partition": case["partition"],
        "turns": turns,
    }
    sealed["digest"] = digest(sealed)
    return sealed


def check(
    checks: list[dict[str, Any]],
    name: str,
    passed: bool,
    stage: str,
    expected: Any,
    observed: Any,
) -> None:
    """Check."""
    checks.append(
        {
            "check": name,
            "passed": bool(passed),
            "failure_stage": None if passed else stage,
            "expected": expected,
            "observed": observed,
        }
    )


def grade_case(
    case: Mapping[str, Any], sealed: Mapping[str, Any], oracle: Mapping[str, Any]
) -> dict[str, Any]:
    """Grade case."""
    checks: list[dict[str, Any]] = []
    receipts = [
        row.get("receipt")
        for row in sealed["turns"]
        if isinstance(row.get("receipt"), Mapping)
    ]
    check(
        checks, "five_receipts", len(receipts) == 5, "dialogue_state", 5, len(receipts)
    )
    indices = [row.get("dialogue_state", {}).get("turn_index") for row in receipts]
    lineage_valid = (
        len(indices) == 5
        and all(isinstance(value, int) for value in indices)
        and all(left < right for left, right in zip(indices, indices[1:]))
    )
    check(
        checks,
        "turn_lineage",
        lineage_valid,
        "dialogue_state",
        "five strictly increasing user-facing turn checkpoints",
        indices,
    )
    check(
        checks,
        "continuations",
        all(row.get("continuation") for row in receipts),
        "dialogue_state",
        True,
        [bool(row.get("continuation")) for row in receipts],
    )
    final = receipts[-1] if receipts else {}
    ledger = final.get("requirement_ledger", {})
    active_requirements = [
        row for row in ledger.get("requirements", ()) if row.get("status") == "active"
    ]
    instantiation = final.get("workflow_instantiation", {})
    nodes = list(instantiation.get("nodes", ()))
    check(
        checks,
        "minimum_requirements",
        len(active_requirements) >= oracle["minimum_active_requirements"],
        "decomposition",
        oracle["minimum_active_requirements"],
        len(active_requirements),
    )
    check(
        checks,
        "requirement_coverage",
        instantiation.get("requirement_coverage_complete") is True,
        "workflow_instantiation",
        "every active requirement owned by a node",
        instantiation.get("requirement_coverage_complete"),
    )
    check(
        checks,
        "minimum_nodes",
        len(nodes) >= oracle["minimum_instantiated_nodes"],
        "workflow_instantiation",
        oracle["minimum_instantiated_nodes"],
        len(nodes),
    )
    observed_components = {
        str((node.get("component") or {}).get("id")).removeprefix("scientific:")
        for node in instantiation.get("nodes", ())
        if (node.get("component") or {}).get("id")
    }
    for group in oracle["acceptable_component_groups"]:
        check(
            checks,
            "component_group:" + "|".join(group),
            bool(observed_components & set(group)),
            "retrieval",
            group,
            sorted(observed_components),
        )
    gaps = list((final.get("capability_gap_plan") or {}).get("gaps", ()))
    plans = {row.get("gap_id") for row in final.get("proposed_skill_test_plans", ())}
    check(
        checks,
        "gap_test_coverage",
        all(gap.get("gap_id") in plans for gap in gaps),
        "gap_planning",
        [gap.get("gap_id") for gap in gaps],
        sorted(value for value in plans if value),
    )
    safe_gaps = all(
        gap.get("availability") == "proposed_unavailable"
        and gap.get("creation_authorized") is False
        and gap.get("catalog_identity") is None
        for gap in gaps
    )
    check(checks, "gap_authority", safe_gaps, "gap_planning", True, safe_gaps)
    cycle = final.get("workflow_refinement_cycle", {})
    check(
        checks,
        "diagnosis_first_refinement",
        isinstance(cycle.get("diagnostic"), Mapping)
        and isinstance(cycle.get("fix_plan"), Mapping),
        "refinement",
        True,
        compact_receipt(final).get("refinement"),
    )
    check(
        checks,
        "release_evidence_gate",
        cycle.get("release_gate") in {"blocked_pending_execution_validation", "passed"},
        "refinement",
        "explicit gate",
        cycle.get("release_gate"),
    )
    check(
        checks,
        "terminal_artifact",
        bool(instantiation.get("terminal_artifact")),
        "workflow_instantiation",
        "non-empty",
        instantiation.get("terminal_artifact"),
    )
    supplied_history: dict[str, list[Any]] = {}
    for turn_row in sealed["turns"]:
        for name, value in turn_row.get("supplied_inputs", {}).items():
            supplied_history.setdefault(name, []).append(value)
    active_inputs = final.get("dialogue_state", {}).get("active_inputs", {})
    for name, values in supplied_history.items():
        check(
            checks,
            f"latest_fact:{name}",
            active_inputs.get(name) == values[-1],
            "dialogue_state",
            values[-1],
            active_inputs.get(name),
        )
    failures = [row for row in checks if not row["passed"]]
    return {
        "case_id": case["case_id"],
        "family_id": case["family_id"],
        "variant": case["variant"],
        "partition": case["partition"],
        "passed": not failures,
        "checks_passed": len(checks) - len(failures),
        "checks_total": len(checks),
        "failure_stages": sorted({row["failure_stage"] for row in failures}),
        "checks": checks,
        "final_summary": compact_receipt(final),
    }
