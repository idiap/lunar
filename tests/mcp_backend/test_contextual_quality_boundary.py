# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0

"""MCP/plugin contextual-quality boundary tests.

This module protects expected behavior for the corresponding workflow, script, or repository surface. Key concepts: regression coverage, interface stability, and output integrity.
"""

import asyncio
import copy
import inspect
import json
import sys
import tomllib
from pathlib import Path

import pytest

from control_plane import tools
from lunar_planner.contracts import seal_quality_contract
from lunar_planner.staged_routing import (
    build_delivery_quality_plan,
    build_outcome_quality_contract,
)
from lunar_planner.quality_authorization import (
    attest_plan_review_result,
    attest_anchor_manifest,
    attest_deterministic_check,
    attest_evaluator_results,
    issue_evaluator_authorization,
    issue_plan_review_authorization,
)

TEST_ONLY_ATTESTATION_KEY = b"bioagents-test-only-quality-key-000000000000000000"


@pytest.fixture(autouse=True)
def _quality_attestation_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Configure a clearly test-only trust root for MCP boundary tests."""

    monkeypatch.setenv("LUNAR_PROFILE", "production")
    monkeypatch.setenv(
        "LUNAR_QUALITY_ATTESTATION_KEY", TEST_ONLY_ATTESTATION_KEY.decode()
    )


def _outcome_plan() -> dict:
    """Build one realistic provisional outcome plan fixture."""

    frame = {
        "goal": "Explain the anti-PD-1 endpoint without claiming a local mechanism.",
        "consumer": "melanoma translational scientist",
        "evidence_scope": ["supplied endpoint table"],
        "prohibited_inference": ["same-lesion mechanism", "treatment advice"],
        "persistent_change_requested": False,
        "intent_units": [{"index": 0, "text": "explain endpoint"}],
        "digest": "sha256:" + "1" * 64,
    }
    ledger = {
        "requirements": [
            {
                "requirement_id": "req-endpoint",
                "status": "active",
                "active_text": "Preserve OR/PFS context and mark lesion-level mechanism as unsupported.",
            }
        ]
    }
    return build_outcome_quality_contract(frame, ledger)


def _specific_outcome_plan() -> dict:
    """Simulate the configured criterion synthesizer's provider-neutral output."""

    plan = _outcome_plan()
    criterion = plan["criteria"][0]
    criterion["observable"] = (
        "The explanation preserves the recorded OR and PFS endpoint context, "
        "states that same-lesion evidence is absent, and does not call the result "
        "proof of a local resistance mechanism."
    )
    return seal_quality_contract(plan)


def _trusted_plan_review(plan: dict, reviewer: dict, producer_id: str) -> dict:
    """Trusted plan review."""
    semantic_review = {
        "plan_digest": plan["digest"],
        "verdict": "pass",
        "independent": True,
        "reviewer_id": reviewer["id"],
        "evaluation_receipts": [
            {
                "phase": "plan_review",
                "request_digest": plan["digest"],
                "status": "pass",
                "evaluator": reviewer,
            }
        ],
    }
    authorization = issue_plan_review_authorization(
        plan,
        reviewer=reviewer,
        criterion_producer_id=producer_id,
        nonce=f"test-{reviewer['id']}",
        trusted_key=TEST_ONLY_ATTESTATION_KEY,
    )
    return {
        "semantic_review": semantic_review,
        "criterion_producer_id": producer_id,
        "review_authorization": authorization,
        "review_attestation": attest_plan_review_result(
            authorization,
            semantic_review,
            trusted_key=TEST_ONLY_ATTESTATION_KEY,
        ),
    }


def _frozen_delivery_plan() -> dict:
    """Review and freeze an outcome plan and its route-bound delivery plan."""

    outcome_plan = _specific_outcome_plan()
    outcome_reviewer = {"id": "quality-reviewer", "kind": "configured_evaluator"}
    reviewed = tools.review_quality_plan_tool(
        outcome_plan,
        reviewer=outcome_reviewer,
        independent=True,
        **_trusted_plan_review(
            outcome_plan, outcome_reviewer, "outcome-criterion-producer"
        ),
    )
    outcome = reviewed["frozen_plan"]
    delivery = build_delivery_quality_plan(
        outcome,
        {"id": "bounded-endpoint-interpreter"},
        {"status": "bound", "inputs": ["endpoint table"]},
    )
    delivery_reviewer = {"id": "delivery-reviewer", "kind": "configured_evaluator"}
    result = tools.review_quality_plan_tool(
        delivery,
        reviewer=delivery_reviewer,
        independent=True,
        **_trusted_plan_review(
            delivery, delivery_reviewer, "delivery-criterion-producer"
        ),
    )
    assert result["review"]["verdict"] == "pass"
    return result["frozen_plan"]


def _passing_results(plan: dict) -> list[dict]:
    """Return anchored passing evaluator results for every plan criterion."""

    return [
        {
            "criterion_id": row["criterion_id"],
            "verdict": "pass",
            "artifact_anchors": ["paragraph:1"],
            "source_anchors": ["endpoint-table:OR", "endpoint-table:PFS"],
            "uncertainty": "low",
        }
        for row in plan["criteria"]
    ]


def _trusted_evidence(
    plan: dict,
    candidate: object,
    results: list[dict],
    evaluator: dict,
    producer_id: str | None,
) -> dict:
    """Trusted evidence."""
    authorization = issue_evaluator_authorization(
        plan,
        candidate,
        evaluator=evaluator,
        producer_id=producer_id,
        nonce="test-fixture",
        trusted_key=TEST_ONLY_ATTESTATION_KEY,
    )
    artifact_anchors = {
        anchor for row in results for anchor in row.get("artifact_anchors", [])
    }
    source_anchors = {
        anchor for row in results for anchor in row.get("source_anchors", [])
    }
    manifest = attest_anchor_manifest(
        authorization,
        artifact_anchors=artifact_anchors,
        source_anchors=source_anchors,
        trusted_key=TEST_ONLY_ATTESTATION_KEY,
    )
    receipts = [
        attest_deterministic_check(
            authorization,
            criterion_id=row["criterion_id"],
            verdict="pass",
            artifact_anchors=["paragraph:1"],
            source_anchors=["endpoint-table:OR"],
            verifier={"id": "test-deterministic-verifier", "configuration": "v1"},
            trusted_key=TEST_ONLY_ATTESTATION_KEY,
        )
        for row in plan["criteria"]
        if row["evaluator_mode"] in {"deterministic", "hybrid"}
    ]
    attestation = attest_evaluator_results(
        authorization, results, manifest, trusted_key=TEST_ONLY_ATTESTATION_KEY
    )
    return {
        "authorization": authorization,
        "result_attestation": attestation,
        "deterministic_receipts": receipts,
        "anchor_manifest": manifest,
    }


def test_quality_review_assessment_and_release_preserve_exact_artifact() -> None:
    """Release only the exact independently assessed candidate."""

    plan = _frozen_delivery_plan()
    candidate = (
        "OR/PFS provide endpoint context; no same-lesion mechanism is established."
    )
    evaluator = {"id": "artifact-critic", "kind": "configured_evaluator"}
    results = _passing_results(plan)
    assessed = tools.assess_quality_candidate_tool(
        plan,
        candidate,
        results,
        evaluator=evaluator,
        producer_id="candidate-producer",
        **_trusted_evidence(plan, candidate, results, evaluator, "candidate-producer"),
    )
    released = tools.decide_quality_delivery_tool(
        plan, assessed["authorized_assessment"], candidate
    )

    assert assessed["assessment"]["verdict"] == "pass"
    assert assessed["provider_call_performed"] is False
    assert released["decision"]["decision"] == "release"
    assert released["released_artifact"] == candidate
    assert released["candidate_withheld"] is False
    assert (
        released["reasoning_log"]["visibility"]["contains_hidden_chain_of_thought"]
        is False
    )

    changed = tools.decide_quality_delivery_tool(
        plan,
        assessed["authorized_assessment"],
        candidate + " This proves local resistance.",
    )
    assert changed["decision"]["decision"] == "inconclusive"
    assert changed["released_artifact"] is None
    assert changed["candidate_withheld"] is True
    assert "artifact changed after assessment" in changed["decision"]["reasons"]


def test_quality_candidate_self_review_is_inconclusive_and_withheld() -> None:
    """A producer cannot release its own material semantic assessment."""

    plan = _frozen_delivery_plan()
    candidate = "OR/PFS context only; lesion mechanism remains unsupported."
    evaluator = {"id": "same-agent", "kind": "configured_evaluator"}
    results = _passing_results(plan)
    assessed = tools.assess_quality_candidate_tool(
        plan,
        candidate,
        results,
        evaluator=evaluator,
        producer_id="same-agent",
        **_trusted_evidence(plan, candidate, results, evaluator, "same-agent"),
    )
    result = tools.decide_quality_delivery_tool(
        plan, assessed["authorized_assessment"], candidate
    )

    assert assessed["assessment"]["independent"] is False
    assert assessed["assessment"]["verdict"] == "inconclusive"
    assert result["presentable_as_user_answer"] is False
    assert result["released_artifact"] is None


def test_material_quality_plan_cannot_freeze_without_semantic_review() -> None:
    """Deterministic lint alone is insufficient for a material plan."""

    result = tools.review_quality_plan_tool(
        _specific_outcome_plan(),
        reviewer={"id": "quality-reviewer", "kind": "configured_evaluator"},
        independent=True,
    )
    assert result["review"]["verdict"] == "inconclusive"
    assert result["frozen_plan"] is None
    assert any(
        "lacks an authenticated independent semantic adequacy review" in finding
        for finding in result["review"]["findings"]
    )


def test_unsigned_or_forged_semantic_review_cannot_freeze_material_plan() -> None:
    """Caller-asserted independence is not evaluator authentication."""

    plan = _specific_outcome_plan()
    reviewer = {"id": "caller-claims-independent", "kind": "configured_evaluator"}
    result = tools.review_quality_plan_tool(
        plan,
        reviewer=reviewer,
        independent=True,
        semantic_review={
            "plan_digest": plan["digest"],
            "verdict": "pass",
            "independent": True,
            "reviewer_id": reviewer["id"],
        },
    )
    assert result["review"]["verdict"] == "inconclusive"
    assert result["frozen_plan"] is None
    assert result["authorized_semantic_review"] is None
    assert any(
        "requires authenticated authorization" in row
        for row in result["review"]["findings"]
    )


@pytest.mark.parametrize("attack", ["result_tamper", "reviewer_substitution"])
def test_plan_review_attestation_rejects_tamper_or_reviewer_substitution(
    attack: str,
) -> None:
    """Verify plan review attestation rejects tamper or reviewer substitution."""
    plan = _specific_outcome_plan()
    reviewer = {"id": "authorized-reviewer", "kind": "configured_evaluator"}
    evidence = _trusted_plan_review(plan, reviewer, "criterion-producer")
    supplied_reviewer = reviewer
    if attack == "result_tamper":
        evidence["semantic_review"] = {
            **evidence["semantic_review"],
            "verdict": "fail",
        }
    else:
        supplied_reviewer = {
            "id": "substituted-reviewer",
            "kind": "configured_evaluator",
        }
        evidence["semantic_review"] = {
            **evidence["semantic_review"],
            "reviewer_id": supplied_reviewer["id"],
        }
    result = tools.review_quality_plan_tool(
        plan,
        reviewer=supplied_reviewer,
        independent=True,
        **evidence,
    )
    assert result["review"]["verdict"] == "inconclusive"
    assert result["frozen_plan"] is None
    assert result["authorized_semantic_review"] is None


def test_plan_review_authorization_rejects_producer_reviewer_identity_collapse() -> (
    None
):
    """Verify plan review authorization rejects producer reviewer identity collapse."""
    plan = _specific_outcome_plan()
    reviewer = {"id": "same-actor", "kind": "configured_evaluator"}
    with pytest.raises(ValueError, match="cannot authorize itself"):
        issue_plan_review_authorization(
            plan,
            reviewer=reviewer,
            criterion_producer_id="same-actor",
            nonce="self-review",
            trusted_key=TEST_ONLY_ATTESTATION_KEY,
        )


def test_deterministic_control_plan_stays_lightweight(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Verify deterministic control plan stays lightweight."""
    log_path = tmp_path / "control-calls.log"
    _configure_counting_adapter(monkeypatch, log_path)
    plan = _specific_outcome_plan()
    plan["risk_tier"] = "control"
    plan = seal_quality_contract(plan)
    result = tools.review_quality_plan_tool(plan)
    assert result["review"]["verdict"] == "pass"
    assert result["frozen_plan"]["lifecycle"] == "frozen"
    assert result["authorized_semantic_review"] is None
    assert result["provider_call_performed"] is False
    assert not log_path.exists()


def _configure_counting_adapter(
    monkeypatch: pytest.MonkeyPatch,
    log_path: Path,
    *,
    disagree_on_second_plan_review: bool = False,
) -> None:
    """Configure counting adapter."""
    program = (
        "import json,pathlib,sys; p=json.load(sys.stdin); phase=p['phase']; "
        "path=pathlib.Path(sys.argv[1]); prior=path.read_text() if path.exists() else ''; "
        "n=sum(1 for row in prior.splitlines() if row==phase)+1; "
        "path.write_text(prior+phase+'\\n'); "
        "plan=p['untrusted_data'].get('quality_plan',{}); "
        "checks={k:True for k in ['coverage','specificity','feasibility','authority','conflicts','architecture_bias']}; "
        "rows=[{'criterion_id':c['criterion_id'],'verdict':'pass','artifact_anchors':['candidate:complete'],"
        "'source_anchors':['authorized:request'],'uncertainty':'low'} for c in plan.get('criteria',[])]; "
        + (
            "status='fail' if phase=='plan_review' and n==2 else 'pass'; "
            if disagree_on_second_plan_review
            else "status='pass'; "
        )
        + "out={'status':status,'checks':checks,'findings':[]} if phase=='plan_review' else "
        "{'status':status,'criterion_results':rows}; json.dump(out,sys.stdout)"
    )
    monkeypatch.setenv(
        "LUNAR_QUALITY_ADAPTER_ARGV",
        json.dumps([sys.executable, "-c", program, str(log_path)]),
    )
    monkeypatch.setenv("LUNAR_QUALITY_ADAPTER_ID", "policy-counting-critic")
    monkeypatch.setenv("LUNAR_QUALITY_ADAPTER_CONFIGURATION", "repeat-test-v1")


def test_complex_policy_executes_review_repeats_and_composition_assessment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Verify complex policy executes review repeats and composition assessment."""
    log_path = tmp_path / "calls.log"
    _configure_counting_adapter(monkeypatch, log_path)
    outcome = _specific_outcome_plan()
    outcome["risk_tier"] = "complex"
    outcome = seal_quality_contract(outcome)
    reviewed = tools.review_quality_plan_tool(outcome)
    assert reviewed["review"]["verdict"] == "pass"
    assert len(reviewed["semantic_review_receipt"]["evaluation_receipts"]) == 2

    frozen_outcome = reviewed["frozen_plan"]
    delivery = build_delivery_quality_plan(
        frozen_outcome,
        {"id": "bounded-endpoint-interpreter"},
        {"status": "bound", "inputs": ["endpoint table"]},
    )
    delivery_review = tools.review_quality_plan_tool(delivery)
    assert delivery_review["review"]["verdict"] == "pass"
    plan = delivery_review["frozen_plan"]
    assessed = tools.assess_quality_candidate_tool(
        plan,
        "OR/PFS are endpoint context; same-lesion mechanism is unsupported.",
        producer_id="candidate-producer",
        authorized_evidence=[
            {
                "source_id": "authorized:request",
                "classification": "bounded_reference",
                "authorized_principal_ids": [plan["principal"]["id"]],
                "content": "request",
            }
        ],
    )
    phases = [row["phase"] for row in assessed["policy_evaluation_receipts"]]
    assert phases.count("artifact_assessment") == 2
    assert phases.count("composition_assessment") == 1
    # The semantic passes cannot override the unavailable authenticated
    # deterministic route/binding receipt.
    assert assessed["assessment"]["verdict"] == "inconclusive"
    assert assessed["authorized_assessment"] is not None


def test_complex_review_disagreement_is_inconclusive(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Verify complex review disagreement is inconclusive."""
    _configure_counting_adapter(
        monkeypatch,
        tmp_path / "disagreement.log",
        disagree_on_second_plan_review=True,
    )
    plan = _specific_outcome_plan()
    plan["risk_tier"] = "complex"
    plan = seal_quality_contract(plan)
    result = tools.review_quality_plan_tool(plan)
    assert result["review"]["verdict"] == "inconclusive"
    assert result["frozen_plan"] is None
    assert result["authorized_semantic_review"] is None
    reconciliation = result["semantic_review_receipt"]["repetition_policy"][
        "reconciliation"
    ]
    assert reconciliation["status"] == "inconclusive"
    assert reconciliation["release_authorized"] is False


def test_bioagents_owned_configured_adapter_is_the_default_quality_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The service can review and assess internally without host-authored verdicts."""

    program = (
        "import json,sys; p=json.load(sys.stdin); phase=p['phase']; "
        "plan=p['untrusted_data'].get('quality_plan',{}); "
        "checks={k:True for k in ['coverage','specificity','feasibility','authority','conflicts','architecture_bias']}; "
        "rows=[{'criterion_id':c['criterion_id'],'verdict':'pass','artifact_anchors':['candidate:complete'],"
        "'source_anchors':['authorized:request'],'uncertainty':'low'} for c in plan.get('criteria',[])]; "
        "out={'status':'pass','checks':checks,'findings':[]} if phase=='plan_review' else "
        "{'status':'pass','criterion_results':rows}; json.dump(out,sys.stdout)"
    )
    monkeypatch.setenv(
        "LUNAR_QUALITY_ADAPTER_ARGV", json.dumps([sys.executable, "-c", program])
    )
    monkeypatch.setenv("LUNAR_QUALITY_ADAPTER_ID", "internal-independent-critic")
    monkeypatch.setenv("LUNAR_QUALITY_ADAPTER_CONFIGURATION", "test-v1")

    reviewed = tools.review_quality_plan_tool(
        _specific_outcome_plan(),
        reviewer={"id": "host-placeholder", "kind": "host"},
        independent=False,
    )
    assert reviewed["review"]["verdict"] == "pass"
    assert reviewed["frozen_plan"]["lifecycle"] == "frozen"
    assert (
        reviewed["semantic_review_receipt"]["reviewer_id"]
        == "internal-independent-critic"
    )
    assert reviewed["provider_call_performed"] is True

    plan = _frozen_delivery_plan()
    candidate = "OR/PFS provide endpoint context; same-lesion mechanism is unsupported."
    assessed = tools.assess_quality_candidate_tool(
        plan,
        candidate,
        producer_id="candidate-producer",
        authorized_evidence=[
            {
                "source_id": "authorized:request",
                "classification": "bounded_reference",
                "authorized_principal_ids": [plan["principal"]["id"]],
                "content": "request",
            }
        ],
    )
    assert assessed["assessment"]["verdict"] == "inconclusive"
    assert assessed["provider_call_performed"] is True
    released = tools.decide_quality_delivery_tool(
        plan, assessed["authorized_assessment"], candidate
    )
    assert released["released_artifact"] is None
    assert released["decision"]["decision"] == "inconclusive"


def test_missing_internal_adapter_returns_typed_inconclusive() -> None:
    """Adapter absence cannot fall back to host-authored or self-asserted passing."""

    result = tools.assess_quality_candidate_tool(
        _frozen_delivery_plan(), "candidate", producer_id="producer"
    )
    assert result["status"] == "inconclusive"
    assert result["assessment"] is None
    assert result["authorized_assessment"] is None
    assert result["presentable_as_user_answer"] is False


def test_quality_surface_inventory_has_one_final_presentation_gate() -> None:
    """Classify all public tools and reserve final presentation for one gate."""

    inventory = tools.quality_surface_inventory_tool()
    rows = inventory["surfaces"]
    finals = [row for row in rows if row["may_present_candidate_as_final"]]

    assert finals == [
        {
            "operation": "lunar_decide_quality_delivery",
            "classification": "final_delivery_gate",
            "starts_quality_cycle": False,
            "may_present_candidate_as_final": True,
            "requires_final_decision_before_presentation": False,
        }
    ]
    candidates = {
        row["operation"]
        for row in rows
        if row["classification"] == "candidate_artifact"
    }
    assert candidates == set()
    assert all(
        row["requires_final_decision_before_presentation"]
        for row in rows
        if row["classification"] == "candidate_artifact"
    )


def test_quality_inventory_covers_the_retained_internal_controls():
    """The public planner retains internal quality checks without domain tools."""
    from mcp.server.fastmcp import FastMCP
    from planner import register_planner_tool

    mcp = FastMCP("inventory-test")
    register_planner_tool(mcp)
    assert {row.name for row in asyncio.run(mcp.list_tools())} == {"planner"}
    assert {
        row["operation"] for row in tools.quality_surface_inventory_tool()["surfaces"]
    } == {
        "lunar_quality_surface_inventory",
        "lunar_review_quality_plan",
        "lunar_assess_quality_candidate",
        "lunar_decide_quality_delivery",
    }


def test_raw_quality_primitives_are_not_public_release_surfaces() -> None:
    """Only authenticated packages cross a registered/public release boundary."""

    import lunar_planner as planner

    assert "assess_quality_artifact" not in planner.__all__
    assert "decide_final_delivery" not in planner.__all__
    assess_parameters = inspect.signature(
        tools.assess_quality_candidate_tool
    ).parameters
    assert {
        "authorization",
        "result_attestation",
        "deterministic_receipts",
        "anchor_manifest",
    } <= set(assess_parameters)
    decide_parameters = inspect.signature(tools.decide_quality_delivery_tool).parameters
    assert "authorized_assessment" in decide_parameters
    assert "assessment" not in decide_parameters

    root = Path(__file__).resolve().parents[2]
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    assert all(
        "staged_routing" not in target
        and "assess_quality_artifact" not in target
        and "decide_final_delivery" not in target
        for target in project["project"].get("scripts", {}).values()
    )


def test_quality_inventory_covers_plugin_and_every_installed_cli() -> None:
    """Keep non-MCP public surfaces inside the same delivery policy inventory."""

    root = Path(__file__).resolve().parents[2]
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    expected_clis = {f"cli:{name}" for name in project["project"].get("scripts", {})}
    rows = tools.quality_surface_inventory_tool()["non_mcp_surfaces"]
    operations = {row["operation"] for row in rows}

    assert operations == expected_clis | {"plugin:lunar-catalog"}
    assert all(row["requires_final_decision_before_presentation"] for row in rows)
    plugin = next(row for row in rows if row["operation"] == "plugin:lunar-catalog")
    assert plugin["starts_quality_cycle"] is True
    assert plugin["may_present_candidate_as_final"] is True


def test_public_surface_policy_rejects_cli_unknown_and_post_release_rewrites() -> None:
    """A CLI label or wrapper rewrite cannot turn an intermediate into final output."""

    from control_plane.quality import require_authorized_biomedical_presentation

    with pytest.raises(ValueError, match="unclassified"):
        require_authorized_biomedical_presentation(
            "cli:bioagents-liver-metastasis-ecosystem",
            {"presentable_as_user_answer": True},
            "candidate",
        )


def test_assessment_rejects_self_addressed_fake_changed_identity_and_unresolved_evidence() -> (
    None
):
    """A valid SHA digest is not an evaluator trust or evidence receipt."""

    from control_plane.quality import require_authorized_biomedical_presentation

    plan = _frozen_delivery_plan()
    candidate = (
        "OR/PFS are endpoint context; same-lesion mechanism remains unsupported."
    )
    evaluator = {
        "id": "configured-artifact-critic",
        "kind": "configured_evaluator",
        "configuration": "critic-v3",
    }
    results = _passing_results(plan)
    trusted = _trusted_evidence(plan, candidate, results, evaluator, "producer")

    fake = copy.deepcopy(trusted["result_attestation"])
    fake["criterion_results_digest"] = "sha256:" + "0" * 64
    fake = seal_quality_contract(fake)  # digest-valid, but not adapter-authenticated
    with pytest.raises(ValueError, match="signature is invalid"):
        tools.assess_quality_candidate_tool(
            plan,
            candidate,
            results,
            evaluator=evaluator,
            producer_id="producer",
            **{**trusted, "result_attestation": fake},
        )

    with pytest.raises(ValueError, match="identity or configuration changed"):
        tools.assess_quality_candidate_tool(
            plan,
            candidate,
            results,
            evaluator={**evaluator, "configuration": "unreviewed-v4"},
            producer_id="producer",
            **trusted,
        )

    fabricated = copy.deepcopy(results)
    fabricated[0]["source_anchors"] = ["invented-source:claim"]
    fabricated_attestation = attest_evaluator_results(
        trusted["authorization"],
        fabricated,
        trusted["anchor_manifest"],
        trusted_key=TEST_ONLY_ATTESTATION_KEY,
    )
    with pytest.raises(ValueError, match="unresolved source anchor"):
        tools.assess_quality_candidate_tool(
            plan,
            candidate,
            fabricated,
            evaluator=evaluator,
            producer_id="producer",
            **{
                **trusted,
                "result_attestation": fabricated_attestation,
            },
        )

    assert trusted["deterministic_receipts"]
    with pytest.raises(ValueError, match="missing authenticated deterministic"):
        tools.assess_quality_candidate_tool(
            plan,
            candidate,
            results,
            evaluator=evaluator,
            producer_id="producer",
            **{**trusted, "deterministic_receipts": []},
        )
    with pytest.raises(ValueError, match="unclassified"):
        require_authorized_biomedical_presentation(
            "cli:unregistered-scientific-answer", None, "candidate"
        )

    plan = _frozen_delivery_plan()
    candidate = {
        "finding": "OR/PFS provide endpoint context",
        "boundary": "same-lesion mechanism is not established",
    }
    evaluator = {"id": "artifact-critic", "kind": "configured_evaluator"}
    results = _passing_results(plan)
    assessed = tools.assess_quality_candidate_tool(
        plan,
        candidate,
        results,
        evaluator=evaluator,
        producer_id="candidate-producer",
        **_trusted_evidence(plan, candidate, results, evaluator, "candidate-producer"),
    )
    released = tools.decide_quality_delivery_tool(
        plan, assessed["authorized_assessment"], candidate
    )
    require_authorized_biomedical_presentation(
        "plugin:lunar-catalog", released, candidate
    )
    require_authorized_biomedical_presentation(
        "lunar_decide_quality_delivery",
        released,
        candidate,
    )
    with pytest.raises(ValueError, match="differs"):
        require_authorized_biomedical_presentation(
            "plugin:lunar-catalog",
            released,
            {**candidate, "boundary": "this proves a local mechanism"},
        )
