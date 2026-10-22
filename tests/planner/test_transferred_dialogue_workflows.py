# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Dialogue regression cases transferred with explicit scientific test metadata."""

import json
from tests.planner.dialogue_transfer_support import (
    FIXTURES as BENCH,
    run_planner_request,
    run_case,
    grade_case,
    read_jsonl,
)


def test_batch_correction_is_not_a_dialogue_correction_marker() -> None:
    """Verify batch correction is not a dialogue correction marker."""
    cases = [
        json.loads(line)
        for line in (BENCH / "cases.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    trace = run_case(
        next(row for row in cases if row["case_id"] == "dialogue-d02-primary")
    )
    final = trace["turns"][-1]["receipt"]
    requirements = final["requirement_ledger"]["requirements"]
    assert any(
        "perturbation-associated state changes" in row["active_text"]
        for row in requirements
    )
    runtime_questions = [
        question
        for question in final["dialogue_state"]["question_history"]
        if str(question.get("intent", "")).startswith("supply:")
    ]
    assert all(question["blocking"] is False for question in runtime_questions)
    assert any(
        str((node.get("component") or {}).get("id")).removeprefix("scientific:")
        in {"pertpy-perturbation-workflows", "within-dataset-omics-contrast-analyst"}
        for node in final["workflow_instantiation"]["nodes"]
    )


def test_finalization_does_not_fill_an_unrelated_missing_port() -> None:
    """Verify finalization does not fill an unrelated missing port."""
    first = run_planner_request(
        "Create an isolated evidence collection",
        supplied_inputs={
            "identity": {"name": "fixture"},
            "profile": {"type": "review"},
        },
    )["planner_receipt"]
    final = run_planner_request(
        "Produce the final workflow and its controlled-execution tests",
        continuation=first["continuation"],
    )["planner_receipt"]
    assert "policy" not in final["dialogue_state"]["active_inputs"]


def test_blocked_refinement_cannot_claim_delivery_readiness() -> None:
    """Verify blocked refinement cannot claim delivery readiness."""
    receipt = run_planner_request(
        "Produce a reusable workflow that imports records from an unknown external service"
    )["planner_receipt"]
    assert (
        receipt["workflow_refinement_cycle"]["release_gate"]
        == "blocked_pending_execution_validation"
    )
    assert receipt["disposition"] != "ready_for_delivery"


def test_final_formal_workflow_orders_construction_before_checking_and_reporting() -> (
    None
):
    """Verify final formal workflow orders construction before checking and reporting."""
    cases = [
        json.loads(line)
        for line in (BENCH / "cases.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    trace = run_case(
        next(row for row in cases if row["case_id"] == "dialogue-d07-primary")
    )
    nodes = trace["turns"][-1]["receipt"]["workflow_instantiation"]["nodes"]
    identifiers = [
        str((node.get("component") or {}).get("id")).removeprefix("scientific:")
        for node in nodes
    ]
    assert "autoformalization-job-builder" in identifiers
    assert identifiers.index("autoformalization-job-builder") < identifiers.index(
        "lean-kernel-runner"
    )
    assert identifiers.index("lean-kernel-runner") < identifiers.index(
        "open-obligation-reporter"
    )
    assert identifiers.index("open-obligation-reporter") < identifiers.index(
        "checked-claim-explainer"
    )


def test_contextual_mechanism_and_private_kb_dialogues_retain_all_responsibilities() -> (
    None
):
    """Keep runtime input gaps from truncating workflow design across later turns."""

    cases = {row["case_id"]: row for row in read_jsonl(BENCH / "cases.jsonl")}
    oracles = {row["case_id"]: row for row in read_jsonl(BENCH / "oracles.jsonl")}
    for case_id in (
        "dialogue-d01-primary",
        "dialogue-d01-contrast",
        "dialogue-d06-primary",
        "dialogue-d06-contrast",
    ):
        trace = run_case(cases[case_id])
        grade = grade_case(cases[case_id], trace, oracles[case_id])
        assert grade["passed"], grade["checks"]
