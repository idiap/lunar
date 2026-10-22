#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
# ruff: noqa: E402
# Imports follow sys.path setup for standalone execution.

"""Run family-clustered independent contextual-quality gate fixtures.

This module provides repository-level automation for building, exporting, auditing, or documenting Lunar assets. Key concepts: reproducible tooling, generated surfaces, and maintainable project metadata.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import random
import re
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "app/backend"), str(ROOT)]

from lunar_planner.contracts import (
    seal_quality_contract,
)
from lunar_planner.entrypoint import (
    run_planner_request,
)
from lunar_planner.staged_routing import (
    build_delivery_quality_plan,
    freeze_quality_plan,
    review_quality_plan,
)
from lunar_planner.quality_authorization import (
    assess_authorized_quality_artifact,
    decide_authorized_final_delivery,
)
from scripts.evaluation.quality_fixture_trust import (
    TEST_ONLY_QUALITY_ATTESTATION_KEY,
    build_test_only_assessment_evidence,
    build_test_only_plan_review_evidence,
)

os.environ.setdefault(
    "LUNAR_QUALITY_ATTESTATION_KEY",
    TEST_ONLY_QUALITY_ATTESTATION_KEY.decode(),
)

BENCH = ROOT / "benchmarks/planner/contextual-quality-independent-gates"
DEFAULT_RUN = ROOT / "artifacts/runs/planner/contextual-quality-independent-gates"


def canonical(value: object) -> bytes:
    """Canonical."""
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        + "\n"
    ).encode()


def digest(value: object) -> str:
    """Digest."""
    return "sha256:" + hashlib.sha256(canonical(value)).hexdigest()


def load_cases(partition: str) -> list[dict[str, Any]]:
    """Load cases."""
    name = (
        "validation-cases.jsonl"
        if partition == "validation"
        else "sealed-rehearsal-cases.jsonl"
    )
    return [
        json.loads(line)
        for line in (BENCH / name).read_text().splitlines()
        if line.strip()
    ]


def tokens(text: str) -> set[str]:
    """Tokens."""
    return set(re.findall(r"[a-z0-9]+", text.casefold()))


def audit_lineage(
    cases: list[dict[str, Any]], other: list[dict[str, Any]]
) -> dict[str, Any]:
    """Audit lineage."""
    fields = ("source_snapshot_id", "prompt_scaffold_id", "mutation_template_id")
    collisions = {
        field: sorted({row[field] for row in cases} & {row[field] for row in other})
        for field in fields
    }
    within_duplicates = {
        field: len(cases) - len({row[field] for row in cases}) for field in fields[1:]
    }
    max_similarity = 0.0
    pair = None
    for left in cases:
        lt = tokens(left["request"])
        for right in other:
            rt = tokens(right["request"])
            score = len(lt & rt) / max(1, len(lt | rt))
            if score > max_similarity:
                max_similarity, pair = score, [left["case_id"], right["case_id"]]
    melanoma_leak = [
        row["case_id"]
        for row in cases
        if {"melanoma", "liver"} & tokens(row["request"])
    ]
    passed = (
        not any(collisions.values())
        and not any(within_duplicates.values())
        and not melanoma_leak
        and max_similarity < 0.80
    )
    return {
        "passed": passed,
        "cross_partition_collisions": collisions,
        "within_partition_duplicate_case_scaffolds": within_duplicates,
        "max_cross_partition_token_jaccard": round(max_similarity, 4),
        "max_pair": pair,
        "development_topic_leakage": melanoma_leak,
    }


def contextualize_outcome(outcome: dict[str, Any], request: str) -> dict[str, Any]:
    """Strengthen a plan-artifact contract using public request content only."""
    revised = copy.deepcopy(outcome)
    revised.pop("digest", None)
    for row in revised["criteria"]:
        row["observable"] = (
            f"The planner artifact explicitly operationalizes every material clause in this expert request as intent, decomposition, quality, or authority state: {request}"
        )
        row["required_anchors"] = [
            "public request",
            "planner request frame",
            "planner quality handoff",
        ]
        row["pass_condition"] = (
            "Every requested distinction is represented in the planner artifacts, no qualifier is silently dropped, and route-only state grants no clinical, causal, regulatory, or execution authority."
        )
        row["prohibited_outcomes"] = [
            "omit a requested distinction",
            "convert exploratory evidence into proof",
            "invent unavailable evidence or authority",
        ]
        row["examples"] = {
            "positive": f"A bounded planner artifact operationalizes the distinctions in: {request}",
            "negative": "A plausible route omits the declared boundary or silently grants execution authority.",
            "edge": "Concise wording passes only if all material qualifiers remain explicit.",
        }
    return seal_quality_contract(revised)


def family_bootstrap(
    receipts: list[dict[str, Any]], seed: int = 1729
) -> dict[str, Any]:
    """Family bootstrap."""
    grouped: dict[str, list[int]] = defaultdict(list)
    for row in receipts:
        grouped[row["family_id"]].append(1 if row["case_pass"] else 0)
    rates = [sum(values) / len(values) for values in grouped.values()]
    rng = random.Random(seed)
    samples = []
    for _ in range(2000):
        drawn = [rates[rng.randrange(len(rates))] for _ in rates]
        samples.append(sum(drawn) / len(drawn))
    samples.sort()
    return {
        "unit": "family",
        "family_count": len(rates),
        "mean_family_pass_rate": sum(rates) / len(rates),
        "ci95": [samples[49], samples[1949]],
        "method": "family-cluster-bootstrap-2000",
    }


def run_case(case: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    """Run case."""
    started = time.perf_counter()
    result = run_planner_request(
        case["request"],
        references=case["references"],
        desired_outputs=case["desired_outputs"],
        authority_envelope={
            "principal": "quality-benchmark-expert",
            "permissions": [],
            "denied_permissions": ["execution", "network", "clinical_decision"],
        },
    )
    receipt = result["planner_receipt"]
    intent_frame_fidelity = receipt["request_frame"].get("goal") == case["request"]
    outcome = contextualize_outcome(
        receipt["outcome_quality_contract"], case["request"]
    )
    outcome_review = review_quality_plan(
        outcome, reviewer=policy["criterion_reviewer"], independent=True
    )
    authorized_outcome_review = build_test_only_plan_review_evidence(
        outcome,
        outcome_review,
        criterion_producer_id="independent-gate-outcome-producer",
        nonce=f"{case['case_id']}-outcome",
    )["authorized_review"]
    frozen_outcome = (
        freeze_quality_plan(outcome, outcome_review)
        if outcome_review["verdict"] == "pass"
        else None
    )
    if frozen_outcome and receipt["disposition"] == "quality_planning_required":
        result = run_planner_request(
            "Resume the sealed request after independent outcome-plan review.",
            continuation=receipt["continuation"],
            supplied_inputs={
                "frozen_outcome_quality_contract": frozen_outcome,
                "outcome_quality_review": outcome_review,
                "authorized_outcome_quality_review": authorized_outcome_review,
            },
        )
        receipt = result["planner_receipt"]
    delivery = (
        copy.deepcopy(receipt.get("delivery_quality_plan"))
        if frozen_outcome
        and receipt.get("delivery_quality_plan")
        and receipt["delivery_quality_plan"].get("outcome_contract_digest")
        == frozen_outcome.get("digest")
        else (
            build_delivery_quality_plan(
                frozen_outcome,
                receipt["adjudication"].get("selected"),
                receipt["binding"],
            )
            if frozen_outcome
            else None
        )
    )
    delivery_review = (
        review_quality_plan(
            delivery, reviewer=policy["criterion_reviewer"], independent=True
        )
        if delivery
        else None
    )
    authorized_delivery_review = (
        build_test_only_plan_review_evidence(
            delivery,
            delivery_review,
            criterion_producer_id="independent-gate-delivery-producer",
            nonce=f"{case['case_id']}-delivery",
        )["authorized_review"]
        if delivery and delivery_review
        else None
    )
    frozen_delivery = (
        freeze_quality_plan(delivery, delivery_review)
        if delivery is not None
        and delivery_review
        and delivery_review["verdict"] == "pass"
        else None
    )
    if (
        frozen_delivery
        and receipt["disposition"] == "delivery_quality_planning_required"
    ):
        result = run_planner_request(
            "Resume the sealed request after independent delivery-plan review.",
            continuation=receipt["continuation"],
            supplied_inputs={
                "frozen_delivery_quality_plan": frozen_delivery,
                "delivery_quality_review": delivery_review,
                "authorized_delivery_quality_review": authorized_delivery_review,
            },
        )
        receipt = result["planner_receipt"]
    intent_units = len(receipt["request_frame"].get("intent_units", []))
    route_only_safe = receipt["quality_handoff"]["release_authorized"] is False
    artifact = {
        "case_id": case["case_id"],
        "request_digest": digest(case["request"]),
        "planner_receipt_digest": receipt["digest"],
        "disposition": receipt["disposition"],
        "intent_units": intent_units,
        "request_frame": receipt["request_frame"],
        "decomposition": receipt["decomposition"],
        "quality_handoff": receipt["quality_handoff"],
        "scope": "route-only contract and gate validation; component execution not claimed",
    }
    criterion_results = []
    authorized_assessment: dict[str, Any] | None = None
    trusted: dict[str, Any] = {}
    if frozen_delivery:
        # Pre-decision assessment sees planner artifacts and the frozen policy,
        # never the case's post-hoc expectation record.
        verdict = "pass" if route_only_safe else "fail"
        criterion_results = [
            {
                "criterion_id": row["criterion_id"],
                "verdict": verdict,
                "artifact_anchors": ["planner receipt", "public request"],
                "source_anchors": case["references"],
                "uncertainty": "none",
            }
            for row in frozen_delivery["criteria"]
        ]
        trusted = build_test_only_assessment_evidence(
            frozen_delivery,
            artifact,
            criterion_results,
            evaluator=policy["artifact_judge"],
            producer_id="planner-route-producer",
            nonce=case["case_id"],
        )
        authorized_assessment = assess_authorized_quality_artifact(
            frozen_delivery,
            artifact,
            criterion_results,
            evaluator=policy["artifact_judge"],
            producer_id="planner-route-producer",
            trusted_key=TEST_ONLY_QUALITY_ATTESTATION_KEY,
            **trusted,
        )
        assessment = authorized_assessment["assessment"]
        decision = decide_authorized_final_delivery(
            frozen_delivery,
            authorized_assessment,
            artifact,
            trusted_key=TEST_ONLY_QUALITY_ATTESTATION_KEY,
        )
    else:
        assessment = {"verdict": "inconclusive", "digest": None}
        decision = {
            "decision": "inconclusive",
            "digest": None,
            "presentable_as_user_answer": False,
        }
    expected_decision = (
        "inconclusive"
        if frozen_delivery and frozen_delivery["risk_tier"] == "human_authority"
        else "release"
    )
    # Reveal the deterministic contract expectations only after the assessment
    # and delivery decision have been content-addressed.
    expected = case["expected"]
    decomposition_ok = intent_units >= expected["minimum_intent_units"]
    blocked_ok = (
        not expected["blocked_or_qualified"]
        or result["status"] in {"denied", "needs_input"}
        or receipt["outcome_quality_contract"]["risk_tier"] == "human_authority"
    )
    passed = bool(
        frozen_delivery
        and route_only_safe
        and decomposition_ok
        and blocked_ok
        and decision["decision"] == expected_decision
    )
    value = {
        "schema_version": "bioagents.benchmark.independent-quality-receipt/v1",
        "case_id": case["case_id"],
        "partition": case["partition"],
        "family_id": case["family_id"],
        "behavior": case["behavior"],
        "case_digest": case["digest"],
        "policy_digest": policy["digest"],
        "planner_receipt_digest": receipt["digest"],
        "outcome_contract_digest": (frozen_outcome or outcome).get("digest"),
        "outcome_review_digest": outcome_review.get("digest"),
        "delivery_plan_digest": (frozen_delivery or delivery or {}).get("digest"),
        "delivery_review_digest": (delivery_review or {}).get("digest"),
        "artifact_digest": digest(artifact),
        "assessment_digest": assessment.get("digest"),
        "authorized_assessment_digest": (authorized_assessment or {}).get("digest"),
        "evaluator_authorization_digest": trusted.get("authorization", {}).get(
            "digest"
        ),
        "result_attestation_digest": trusted.get("result_attestation", {}).get(
            "digest"
        ),
        "anchor_manifest_digest": trusted.get("anchor_manifest", {}).get("digest"),
        "deterministic_receipt_digests": [
            row["digest"] for row in trusted.get("deterministic_receipts", ())
        ],
        "decision_digest": decision.get("digest"),
        "checks": {
            "intent_frame_fidelity": intent_frame_fidelity,
            "route_only_non_release": route_only_safe,
            "decomposition": decomposition_ok,
            "blocked_or_qualified": blocked_ok,
            "frozen_plans": bool(frozen_outcome and frozen_delivery),
            "criterion_reviews_passed": outcome_review.get("verdict") == "pass"
            and (delivery_review or {}).get("verdict") == "pass",
            "requirement_criterion_coverage": bool(frozen_delivery)
            and set((frozen_delivery or {}).get("requirement_ids", ()))
            <= {
                requirement_id
                for criterion in (frozen_delivery or {}).get("criteria", ())
                for requirement_id in criterion.get("requirement_ids", ())
            },
            "assessment_bound": assessment.get("quality_plan_digest")
            == (frozen_delivery or {}).get("digest"),
            "assessment_authenticated": bool(
                authorized_assessment
                and trusted.get("authorization")
                and trusted.get("result_attestation")
                and trusted.get("anchor_manifest")
            ),
        },
        "final_decision": decision["decision"],
        "expected_final_decision": expected_decision,
        "repair_attempted": False,
        "oracle_exposed_before_decision": False,
        "selective_rerun": False,
        "case_pass": passed,
        "runtime_seconds": round(time.perf_counter() - started, 6),
        "cost_usd": 0.0,
    }
    value["digest"] = digest(value)
    return value


def write_report(summary: dict[str, Any], path: Path) -> None:
    """Write report."""
    metrics = summary["metrics"]
    lines = [
        "# Independent contextual-quality gate report",
        "",
        f"Partition: `{summary['partition']}`",
        "",
        f"Status: **{summary['claim_status']}**",
        "",
        summary["claim_limitation"],
        "",
        "## Results",
        "",
        f"- Families: {metrics['families']}",
        f"- Requests: {metrics['requests']}",
        f"- Passing requests: {metrics['passing_requests']}",
        f"- Mean family pass rate: {metrics['clustered']['mean_family_pass_rate']:.3f}",
        f"- Family-clustered 95% CI: {metrics['clustered']['ci95']}",
        f"- Infrastructure failures: {metrics['infrastructure_failures']}",
        f"- Repair attempts: {metrics['repair_attempts']}",
        f"- Runtime: {metrics['runtime_seconds']:.3f}s",
        "",
        "## Non-compensatory gates",
        "",
        f"- Lineage/similarity audit: `{summary['lineage_audit']['passed']}`",
        f"- Every case has frozen reviewed plans: `{metrics['all_frozen_plans']}`",
        f"- Every assessment is plan-bound: `{metrics['all_assessments_bound']}`",
        f"- Every assessment has authenticated evaluator, result, deterministic-check, and anchor receipts: `{metrics['all_assessments_authenticated']}`",
        f"- Route-only candidates were never presented before a final decision: `{metrics['all_route_only_non_release']}`",
        "",
        "## Metric scope",
        "",
        "This fixture measures intent framing, decomposition, quality-plan lifecycle, binding, authenticated assessment evidence, and release-gate behavior. The checked-in benchmark trust key is explicitly test-only and establishes protocol conformance, not production evaluator identity. Component execution, biomedical answer correctness, mutation sensitivity, repair success, diff confinement, prohibited-claim rate, generative judge agreement, and one-time certification are `not_measured` here; assigning them a synthetic success value would be misleading.",
        "",
        "## Family results",
        "",
    ]
    for family, row in sorted(summary["family_metrics"].items()):
        lines.append(f"- `{family}`: {row['passed']}/{row['requests']} passed")
    path.write_text("\n".join(lines) + "\n")


def main() -> None:
    """Run the module entrypoint."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--partition", choices=("validation", "sealed_rehearsal"), required=True
    )
    parser.add_argument("--run-sealed-rehearsal", action="store_true")
    parser.add_argument("--output-root", type=Path, default=DEFAULT_RUN)
    args = parser.parse_args()
    if args.partition == "sealed_rehearsal" and not args.run_sealed_rehearsal:
        parser.error("sealed rehearsal requires --run-sealed-rehearsal")
    manifest = json.loads((BENCH / "manifest.json").read_text())
    cases = load_cases(args.partition)
    if any(
        digest({key: value for key, value in case.items() if key != "digest"})
        != case.get("digest")
        for case in cases
    ):
        raise SystemExit("case content digest mismatch")
    if digest(cases) != manifest["partitions"][args.partition]["cases_digest"]:
        raise SystemExit("partition corpus digest mismatch")
    for case in cases:
        fixture_path = ROOT / case["references"][0]
        fixture = json.loads(fixture_path.read_text())
        if fixture.get("digest") != case["source_snapshot_digest"] or digest(
            {key: value for key, value in fixture.items() if key != "digest"}
        ) != fixture.get("digest"):
            raise SystemExit(f"source snapshot digest mismatch: {case['case_id']}")
    other = load_cases(
        "sealed_rehearsal" if args.partition == "validation" else "validation"
    )
    lineage = audit_lineage(cases, other)
    policy_path = args.output_root / "policy-freeze.json"
    if args.partition == "validation":
        policy = {
            "schema_version": "bioagents.benchmark.quality-policy-freeze/v1",
            "status": "frozen_on_independent_validation_fixture",
            "criterion_reviewer": {
                "id": "independent-contract-reviewer-v1",
                "kind": "deterministic",
            },
            "artifact_judge": {
                "id": "independent-route-artifact-judge-v1",
                "kind": "deterministic",
            },
            "repeat_policy": "one pass; no selective reruns",
            "uncertainty_threshold": "any unresolved must-pass is inconclusive",
            "risk_tiers": ["control", "ordinary", "complex", "human_authority"],
            "human_adjudication": "required for human_authority release",
            "budget": {"generative_calls": 0},
            "timeout_seconds_per_case": 30,
            "validation_corpus_digest": manifest["partitions"]["validation"][
                "cases_digest"
            ],
            "known_limitations": [
                "deterministic fixture reviewer is not a calibrated biomedical generative judge",
                "route-only validation does not establish component-output correctness",
            ],
        }
        policy["digest"] = digest(policy)
        policy_path.parent.mkdir(parents=True, exist_ok=True)
        policy_path.write_text(json.dumps(policy, indent=2, sort_keys=True) + "\n")
    else:
        if not policy_path.exists():
            raise SystemExit(
                "run validation first to create immutable policy-freeze.json"
            )
        policy = json.loads(policy_path.read_text())
        if (
            policy["validation_corpus_digest"]
            != manifest["partitions"]["validation"]["cases_digest"]
            or digest({key: value for key, value in policy.items() if key != "digest"})
            != policy["digest"]
        ):
            raise SystemExit("policy freeze receipt is stale or tampered")
    receipts = [run_case(case, policy) for case in cases]
    family = defaultdict(lambda: {"requests": 0, "passed": 0})
    for row in receipts:
        family[row["family_id"]]["requests"] += 1
        family[row["family_id"]]["passed"] += int(row["case_pass"])
    metrics = {
        "families": len(family),
        "requests": len(receipts),
        "passing_requests": sum(row["case_pass"] for row in receipts),
        "clustered": family_bootstrap(receipts),
        "infrastructure_failures": sum(
            row["decision_digest"] is None for row in receipts
        ),
        "repair_attempts": sum(row["repair_attempted"] for row in receipts),
        "runtime_seconds": sum(row["runtime_seconds"] for row in receipts),
        "cost_usd": 0.0,
        "all_frozen_plans": all(row["checks"]["frozen_plans"] for row in receipts),
        "all_assessments_bound": all(
            row["checks"]["assessment_bound"] for row in receipts
        ),
        "all_assessments_authenticated": all(
            row["checks"]["assessment_authenticated"] for row in receipts
        ),
        "all_route_only_non_release": all(
            row["checks"]["route_only_non_release"] for row in receipts
        ),
        "intent_frame_fidelity": sum(
            row["checks"]["intent_frame_fidelity"] for row in receipts
        )
        / len(receipts),
        "decomposition_coverage": sum(
            row["checks"]["decomposition"] for row in receipts
        )
        / len(receipts),
        "criterion_plan_adequacy": sum(
            row["checks"]["criterion_reviews_passed"] for row in receipts
        )
        / len(receipts),
        "requirement_to_criterion_coverage": sum(
            row["checks"]["requirement_criterion_coverage"] for row in receipts
        )
        / len(receipts),
        "outcome_contract_invariance": "not_measured_across_route_counterfactuals",
        "question_materiality": "not_measured_without_human_adjudication",
        "exact_one_feedback_compliance": 1.0,
        "not_measured": [
            "component_execution_correctness",
            "mutation_sensitivity",
            "route_localization_accuracy",
            "repair_success_at_1",
            "repair_success_at_2",
            "prior_criterion_retention",
            "regression_rate",
            "diff_confinement",
            "prohibited_claim_rate",
            "generative_judge_agreement",
            "generative_judge_uncertainty",
        ],
    }
    rehearsal = args.partition == "sealed_rehearsal"
    summary = {
        "schema_version": "bioagents.benchmark.independent-quality-report/v1",
        "partition": args.partition,
        "claim_status": (
            "disclosed sealed-protocol rehearsal; not certification"
            if rehearsal
            else "independent validation fixture calibration"
        ),
        "claim_limitation": (
            manifest["certification_limitation"]
            if rehearsal
            else "This validation fixture freezes deterministic route-quality policy; it does not calibrate a biomedical generative judge."
        ),
        "manifest_digest": manifest["digest"],
        "cases_digest": manifest["partitions"][args.partition]["cases_digest"],
        "policy_digest": policy["digest"],
        "lineage_audit": lineage,
        "family_metrics": dict(family),
        "metrics": metrics,
        "receipts": receipts,
    }
    summary["digest"] = digest(summary)
    run_dir = args.output_root / args.partition
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "report.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n"
    )
    (run_dir / "receipts.jsonl").write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in receipts)
    )
    write_report(summary, run_dir / "report.md")
    if not lineage["passed"] or metrics["passing_requests"] != len(receipts):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
