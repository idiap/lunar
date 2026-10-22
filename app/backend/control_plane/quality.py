# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0

"""Provider-neutral quality-control projections for MCP and plugin clients.

The functions in this module expose typed planner quality artifacts and concise
decision summaries. They do not call a model, run a subprocess, or infer a
criterion verdict; an authorized evaluator supplies per-criterion results.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from typing import Any

from lunar_planner.contracts import (
    require_valid_contract,
    seal_quality_contract,
)
from lunar_planner.quality_authorization import (
    assess_authorized_quality_artifact,
    attest_anchor_manifest,
    attest_deterministic_check,
    attest_evaluator_results,
    attest_plan_review_result,
    decide_authorized_final_delivery,
    issue_evaluator_authorization,
    issue_plan_review_authorization,
    verify_authorized_plan_review,
)
from lunar_planner.quality_evaluation import (
    ConfiguredCommandQualityAdapter,
    evaluate_with_adapter,
    plan_review_evaluation_receipts_sufficient,
    reconcile_quality_evaluator_results,
)
from lunar_planner.quality_governance import (
    RISK_POLICIES,
)
from lunar_planner.staged_routing import (
    build_quality_repair,
    freeze_quality_plan,
    review_quality_plan,
)

from platform_runtime.reasoning_log import (
    build_reasoning_log,
    render_reasoning_log_markdown,
)

from .quality_runtime import get_quality_runtime

_CONTROL_SURFACES = {
    "lunar_quality_surface_inventory": "quality_control",
    "lunar_review_quality_plan": "quality_control",
    "lunar_assess_quality_candidate": "quality_control",
    "lunar_decide_quality_delivery": "final_delivery_gate",
}

# Public interfaces which do not appear in ``FastMCP.list_tools()`` still need
# an explicit delivery classification.  Keep this list synchronized with
# ``pyproject.toml [project.scripts]`` and the one conversational plugin skill.
# A workflow CLI can emit a scientific artifact for an explicitly invoked
# local process, but that artifact is not thereby a released conversational
# Lunar answer.
_NON_MCP_SURFACES = {
    "plugin:lunar-catalog": {
        "surface_kind": "conversational_adapter",
        "classification": "conversational_adapter",
        "starts_quality_cycle": True,
        "may_present_candidate_as_final": True,
        "requires_final_decision_before_presentation": True,
    }
}


def _artifact_digest(value: Any) -> str:
    """Match the planner's canonical digest for one JSON-compatible payload."""

    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _trusted_attestation_key() -> bytes:
    """Load the deployment-owned evaluator attestation key."""

    value = os.environ.get("LUNAR_QUALITY_ATTESTATION_KEY", "")
    if len(value.encode("utf-8")) < 32:
        raise ValueError(
            "LUNAR_QUALITY_ATTESTATION_KEY must be configured with at least 32 bytes"
        )
    return value.encode("utf-8")


def _configured_internal_adapter() -> Any | None:
    """Return the adapter selected by the server-owned quality runtime."""

    return get_quality_runtime().adapter


def _validate_internal_result_anchors(
    candidate: Any,
    authorized_evidence: Sequence[Mapping[str, Any]],
    rows: Sequence[Mapping[str, Any]],
) -> None:
    """Resolve adapter locators before the service attests them."""

    source_ids = {
        str(row.get("source_id")) for row in authorized_evidence if row.get("source_id")
    }
    paragraphs = max(
        1, len([part for part in str(candidate).split("\n\n") if part.strip()])
    )
    candidate_keys = (
        set(map(str, candidate)) if isinstance(candidate, Mapping) else set()
    )
    for row in rows:
        for anchor in map(str, row.get("artifact_anchors", ())):
            valid = anchor == "candidate:complete"
            if anchor.startswith("paragraph:"):
                try:
                    valid = 1 <= int(anchor.split(":", 1)[1]) <= paragraphs
                except ValueError:
                    valid = False
            elif anchor.startswith("field:"):
                valid = anchor.split(":", 1)[1] in candidate_keys
            if not valid:
                raise ValueError(
                    f"quality_assessment_inconclusive: unresolved artifact anchor {anchor}"
                )
        for anchor in map(str, row.get("source_anchors", ())):
            if not any(
                anchor == source_id or anchor.startswith(source_id + ":")
                for source_id in source_ids
            ):
                raise ValueError(
                    f"quality_assessment_inconclusive: unresolved source anchor {anchor}"
                )


def require_authorized_biomedical_presentation(
    surface: str,
    final_delivery: Mapping[str, Any] | None,
    presented_artifact: Any,
) -> None:
    """Fail closed unless a public surface presents the exact released payload.

    MCP candidate tools and standalone CLIs may produce intermediate artifacts,
    but only the final MCP gate or the plugin adapter may present a semantic
    payload as a Lunar conversational answer.  The adapter must preserve
    the released artifact byte-for-byte at the canonical JSON level.
    """

    known = {
        **{
            name: {"surface_kind": "mcp", "classification": kind}
            for name, kind in _CONTROL_SURFACES.items()
        },
        **_NON_MCP_SURFACES,
    }
    if surface not in known:
        raise ValueError(f"unclassified public presentation surface: {surface}")
    if surface not in {"lunar_decide_quality_delivery", "plugin:lunar-catalog"}:
        raise ValueError(f"{surface} cannot present a biomedical candidate as final")
    if not isinstance(final_delivery, Mapping):
        raise ValueError("a final quality-delivery envelope is required")
    decision = final_delivery.get("decision")
    released = final_delivery.get("released_artifact")
    if (
        final_delivery.get("schema_version") != "lunar.mcp.final-quality-delivery/v1"
        or final_delivery.get("presentable_as_user_answer") is not True
        or not isinstance(decision, Mapping)
        or decision.get("schema_version") != "lunar.planner.final-delivery-decision/v1"
        or decision.get("decision") != "release"
        or released is None
    ):
        raise ValueError(
            "the final quality-delivery envelope does not authorize release"
        )
    released_digest = _artifact_digest(released)
    if decision.get("artifact_digest") != released_digest:
        raise ValueError("the release decision does not bind the released artifact")
    if _artifact_digest(presented_artifact) != released_digest:
        raise ValueError(
            "the presented artifact differs from the assessed release payload"
        )


def quality_surface_inventory() -> dict[str, object]:
    """Return the exhaustive MCP plus CLI/plugin delivery classification."""

    rows = []
    for name, classification in sorted(_CONTROL_SURFACES.items()):
        rows.append(
            {
                "operation": name,
                "classification": classification,
                "starts_quality_cycle": name == "lunar_plan_request",
                "may_present_candidate_as_final": name
                == "lunar_decide_quality_delivery",
                "requires_final_decision_before_presentation": classification
                == "candidate_artifact",
            }
        )
    non_mcp_rows = []
    for name, policy in sorted(_NON_MCP_SURFACES.items()):
        classification = str(policy["classification"])
        non_mcp_rows.append(
            {
                "operation": name,
                "surface_kind": policy["surface_kind"],
                "classification": classification,
                "starts_quality_cycle": bool(policy.get("starts_quality_cycle", False)),
                "may_present_candidate_as_final": bool(
                    policy.get("may_present_candidate_as_final", False)
                ),
                "requires_final_decision_before_presentation": bool(
                    policy.get("requires_final_decision_before_presentation", True)
                ),
            }
        )
    return {
        "schema_version": "lunar.mcp.quality-surface-inventory/v1",
        "surfaces": rows,
        "non_mcp_surfaces": non_mcp_rows,
        "surface_count": len(rows) + len(non_mcp_rows),
        "invariant": (
            "Only lunar_decide_quality_delivery may release a candidate; the "
            "Lunar plugin may present only that exact released artifact. "
            "Standalone CLIs never imply conversational release."
        ),
        "execution_performed": False,
    }


def _quality_summary(
    plan: Mapping[str, Any],
    *,
    review: Mapping[str, Any] | None = None,
    assessment: Mapping[str, Any] | None = None,
    decision: Mapping[str, Any] | None = None,
) -> dict[str, object]:
    """Project quality artifacts into a bounded user-readable summary."""

    criteria = list(plan.get("criteria", ()))
    outcome = {
        "quality_plan_digest": plan.get("digest"),
        "quality_plan_kind": plan.get("schema_version"),
        "risk_tier": plan.get("risk_tier"),
        "criterion_count": len(criteria),
        "must_pass_criteria": [
            {
                "criterion_id": row.get("criterion_id"),
                "observable": row.get("observable"),
                "source": row.get("source"),
                "consumer": row.get("consumer"),
                "failure_consequence": row.get("failure_consequence"),
            }
            for row in criteria
            if row.get("severity") == "must_pass"
        ],
        "review_verdict": (review or {}).get("verdict"),
        "assessment_verdict": (assessment or {}).get("verdict"),
        "decision": (decision or {}).get("decision"),
        "decision_reasons": list((decision or {}).get("reasons", ())),
        "uncertainty": [
            {
                "criterion_id": row.get("criterion_id"),
                "verdict": row.get("verdict"),
                "uncertainty": row.get("uncertainty"),
            }
            for row in (assessment or {}).get("criterion_results", ())
            if row.get("verdict") != "pass"
        ],
        "evidence_anchors": [
            {
                "criterion_id": row.get("criterion_id"),
                "artifact_anchors": list(row.get("artifact_anchors", ())),
                "source_anchors": list(row.get("source_anchors", ())),
            }
            for row in (assessment or {}).get("criterion_results", ())
        ],
    }
    return outcome


def _reasoning_projection(
    plan: Mapping[str, Any],
    summary: Mapping[str, Any],
    *,
    assessment: Mapping[str, Any] | None = None,
    decision: Mapping[str, Any] | None = None,
) -> tuple[dict[str, object], str]:
    """Build a normalized audit summary without private evaluator reasoning."""

    decision_value = str((decision or {}).get("decision") or "reviewed")
    decision_status = (
        "blocked"
        if decision_value in {"block", "revise", "inconclusive", "needs_input"}
        else "accepted"
    )
    status = (
        "blocked"
        if decision_value in {"block", "revise", "inconclusive", "needs_input"}
        else ("completed" if decision_value == "release" else "planned")
    )
    log = build_reasoning_log(
        subject_kind="planner",
        subject_id=str(
            plan.get("plan_id") or plan.get("contract_id") or "quality-plan"
        ),
        summary=(
            f"Lunar evaluated {summary['criterion_count']} contextual criterion(s); "
            f"the current disposition is {decision_value}."
        ),
        status=status,
        events=[
            {
                "stage": "contextual quality control",
                "actor": {"kind": "deterministic_check", "id": "lunar-quality-gate"},
                "action": "Validated criterion coverage and artifact-bound evaluation receipts.",
                "rationale_summary": "Only public criterion outcomes, evidence locators, uncertainty, and digest bindings are surfaced.",
                "inputs_used": [str(plan.get("digest"))],
                "decision": {
                    "status": decision_status,
                    "outcome": str(
                        (decision or {}).get("next_action") or "quality plan reviewed"
                    ),
                    "alternatives_considered": [],
                },
                "outputs": [
                    "quality summary",
                    "final delivery decision" if decision else "quality review",
                ],
                "checks": [
                    str(row.get("criterion_id"))
                    for row in (assessment or {}).get("criterion_results", ())
                ],
                "blockers": list((decision or {}).get("reasons", ())),
            }
        ],
        evidence_references=[
            {
                "id": "quality-plan",
                "kind": "contract",
                "locator": str(plan.get("schema_version")),
                "description": "Frozen contextual quality plan used for evaluation.",
                "digest": str(plan.get("digest", "")),
            }
        ],
        blockers=list((decision or {}).get("reasons", ())),
        limitations=[
            "This is a concise decision trace, not hidden chain-of-thought or evaluator scratch work.",
            "Evidence locators do not grant access to source bodies.",
        ],
    )
    return log, render_reasoning_log_markdown(log)


def _evaluation_policy(plan: Mapping[str, Any]) -> dict[str, Any]:
    """Resolve the declared risk policy carried by one frozen/provisional plan."""

    tier = str(plan.get("risk_tier", "ordinary"))
    return {"tier": tier, **RISK_POLICIES.get(tier, RISK_POLICIES["ordinary"])}


def _run_configured_repetitions(
    adapter: ConfiguredCommandQualityAdapter,
    phase: str,
    *,
    plan: Mapping[str, Any],
    context: Mapping[str, Any],
    required_repetitions: int | None = None,
) -> dict[str, Any]:
    """Execute every policy-required repetition and reconcile without voting."""

    policy = _evaluation_policy(plan)
    required = max(
        1,
        int(
            required_repetitions
            if required_repetitions is not None
            else (policy.get("repeats", 1) or 1)
        ),
    )
    if required > int(policy.get("cost_ceiling_units", required) or 0):
        return {
            "phase": phase,
            "required_repetitions": required,
            "completed_repetitions": 0,
            "receipts": [],
            "reconciliation": {
                "status": "inconclusive",
                "reason": "evaluation_budget_insufficient",
                "release_authorized": False,
            },
            "status": "inconclusive",
        }
    receipts = [
        evaluate_with_adapter(
            adapter,
            phase,
            principal=dict(plan.get("principal", {})),
            context=context,
        )
        for _index in range(required)
    ]
    reconciliation = reconcile_quality_evaluator_results(receipts)
    return {
        "phase": phase,
        "required_repetitions": required,
        "completed_repetitions": len(receipts),
        "receipts": receipts,
        "reconciliation": reconciliation,
        "status": reconciliation.get("status", "inconclusive"),
    }


def _policy_review_is_sufficient(
    plan: Mapping[str, Any],
    semantic_review: Mapping[str, Any],
    *,
    criterion_producer_id: str | None = None,
    reviewer: Mapping[str, Any] | None = None,
) -> bool:
    """Require declared repetitions for non-control semantic plan reviews."""

    policy = _evaluation_policy(plan)
    required = max(1, int(policy.get("repeats", 1) or 1))
    return plan_review_evaluation_receipts_sufficient(
        semantic_review,
        required_repetitions=required,
        criterion_producer_id=criterion_producer_id,
        reviewer=reviewer,
    )


def _reconcile_criterion_results(
    phase_runs: Sequence[Mapping[str, Any]], expected_ids: set[str]
) -> tuple[list[dict[str, Any]] | None, str | None]:
    """Require criterion-verdict agreement across every required phase/run."""

    all_receipts = [
        dict(receipt) for phase in phase_runs for receipt in phase.get("receipts", ())
    ]
    if not all_receipts or any(
        phase.get("status") not in {"pass", "fail"} for phase in phase_runs
    ):
        return None, "required evaluator repetitions are unavailable or disagree"
    by_run: list[dict[str, str]] = []
    for receipt in all_receipts:
        values = {
            str(row.get("criterion_id")): str(row.get("verdict"))
            for row in receipt.get("criterion_results", ())
        }
        if set(values) != expected_ids:
            return (
                None,
                "a policy-required evaluator run has incomplete criterion coverage",
            )
        by_run.append(values)
    for criterion_id in sorted(expected_ids):
        if len({values[criterion_id] for values in by_run}) != 1:
            return None, f"evaluator disagreement for criterion {criterion_id}"
    return [dict(row) for row in all_receipts[0].get("criterion_results", ())], None


def review_quality_plan_operation(
    plan: Mapping[str, Any],
    *,
    reviewer: Mapping[str, Any] | None,
    independent: bool,
    semantic_review: Mapping[str, Any] | None = None,
    criterion_producer_id: str | None = None,
    review_authorization: Mapping[str, Any] | None = None,
    review_attestation: Mapping[str, Any] | None = None,
) -> dict[str, object]:
    """Review and freeze an outcome or delivery plan when adequacy passes."""

    require_valid_contract(plan)
    material = plan.get("risk_tier") != "control"
    reviewer = dict(
        reviewer
        or (
            {"id": "planner-quality-linter", "kind": "deterministic"}
            if not material
            else {"id": "quality-review-unavailable", "kind": "control"}
        )
    )
    if not material:
        independent = True
    internal_adapter_used = False
    adapter = (
        _configured_internal_adapter() if material and semantic_review is None else None
    )
    if adapter is not None:
        internal_adapter_used = True
        policy_run = _run_configured_repetitions(
            adapter,
            "plan_review",
            plan=plan,
            context={"quality_plan": dict(plan), "authorized_evidence": []},
        )
        adapter_results = list(policy_run["receipts"])
        first_result = adapter_results[0] if adapter_results else {}
        adapter_status = str(policy_run["status"])
        reviewer = dict(adapter.identity)
        independent = True
        semantic_review = {
            "plan_digest": plan.get("digest"),
            "verdict": adapter_status,
            "independent": adapter_status in {"pass", "fail"},
            "reviewer_id": adapter.identity["id"],
            "checks": first_result.get("checks", {}),
            "findings": [
                finding
                for result in adapter_results
                for finding in result.get("findings", ())
            ],
            "evaluation_receipts": adapter_results,
            "repetition_policy": {
                "required": policy_run["required_repetitions"],
                "completed": policy_run["completed_repetitions"],
                "reconciliation": policy_run["reconciliation"],
            },
        }
        # Internal review authorization uses the service-owned producer role;
        # a caller cannot choose a convenient distinct identity.
        criterion_producer_id = "lunar-criterion-synthesizer"
        review_authorization = issue_plan_review_authorization(
            plan,
            reviewer=reviewer,
            criterion_producer_id=criterion_producer_id,
            nonce=str(plan.get("digest", "unknown"))[-16:],
            trusted_key=_trusted_attestation_key(),
        )
        review_attestation = attest_plan_review_result(
            review_authorization,
            semantic_review,
            trusted_key=_trusted_attestation_key(),
        )
    review = review_quality_plan(plan, reviewer=reviewer, independent=independent)
    authorized_review = None
    authorization_error = None
    if material and semantic_review:
        try:
            if (
                not criterion_producer_id
                or not review_authorization
                or not review_attestation
            ):
                raise ValueError(
                    "material semantic review requires authenticated authorization and attestation"
                )
            authorized_review = verify_authorized_plan_review(
                plan,
                semantic_review,
                reviewer=reviewer,
                criterion_producer_id=criterion_producer_id,
                authorization=review_authorization,
                result_attestation=review_attestation,
                trusted_key=_trusted_attestation_key(),
            )
        except ValueError as exc:
            authorization_error = str(exc)
    semantic_valid = bool(
        authorized_review
        and semantic_review
        and semantic_review.get("verdict") == "pass"
        and _policy_review_is_sufficient(
            plan,
            semantic_review,
            criterion_producer_id=criterion_producer_id,
            reviewer=reviewer,
        )
    )
    if material and not semantic_valid:
        failed_semantic_review = bool(
            authorized_review
            and semantic_review is not None
            and semantic_review.get("verdict") == "fail"
        )
        review = seal_quality_contract(
            {
                **review,
                "verdict": (
                    "fail"
                    if review.get("verdict") == "fail" or failed_semantic_review
                    else "inconclusive"
                ),
                "findings": [
                    *review.get("findings", ()),
                    (
                        "material quality plan lacks an authenticated independent semantic adequacy review"
                        + (f": {authorization_error}" if authorization_error else "")
                    ),
                ],
            }
        )
    frozen_plan = (
        freeze_quality_plan(plan, review) if review["verdict"] == "pass" else None
    )
    effective_plan = frozen_plan or plan
    summary = _quality_summary(effective_plan, review=review)
    log, markdown = _reasoning_projection(effective_plan, summary)
    return {
        "schema_version": "lunar.mcp.quality-plan-review/v1",
        "operation_role": "criterion_review",
        "control_traffic": True,
        "presentable_as_user_answer": False,
        "review": review,
        "semantic_review_receipt": dict(semantic_review or {}),
        "authorized_semantic_review": authorized_review,
        "frozen_plan": frozen_plan,
        "quality_summary": summary,
        "reasoning_log": log,
        "reasoning_log_markdown": markdown,
        "execution_performed": False,
        "provider_call_performed": internal_adapter_used,
        "evaluation_policy": _evaluation_policy(plan),
    }


def assess_quality_candidate_operation(
    plan: Mapping[str, Any],
    candidate_artifact: Any,
    criterion_results: Sequence[Mapping[str, Any]] | None,
    *,
    evaluator: Mapping[str, Any] | None,
    producer_id: str | None,
    authorization: Mapping[str, Any] | None,
    result_attestation: Mapping[str, Any] | None,
    deterministic_receipts: Sequence[Mapping[str, Any]] | None,
    anchor_manifest: Mapping[str, Any] | None,
    authorized_evidence: Sequence[Mapping[str, Any]] | None = None,
    trusted_deterministic_results: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, object]:
    """Bind evaluator-supplied results to one frozen plan and exact candidate."""

    require_valid_contract(plan)
    rows = [dict(row) for row in (criterion_results or ())]
    internal_adapter_used = False
    policy_evaluation_receipts: list[dict[str, Any]] = []
    if authorization is None or result_attestation is None or anchor_manifest is None:
        adapter = _configured_internal_adapter()
        if adapter is None:
            return {
                "schema_version": "lunar.mcp.quality-candidate-assessment/v1",
                "operation_role": "artifact_assessment",
                "control_traffic": True,
                "presentable_as_user_answer": False,
                "status": "inconclusive",
                "reason": "quality_assessment_inconclusive: no internal adapter or authenticated external receipts",
                "assessment": None,
                "authorized_assessment": None,
                "execution_performed": False,
                "provider_call_performed": False,
            }
        evaluation_context = {
            "quality_plan": dict(plan),
            "candidate_artifact": candidate_artifact,
            "authorized_evidence": list(authorized_evidence or ()),
            "deterministic_results": list(trusted_deterministic_results or ()),
        }
        policy = _evaluation_policy(plan)
        planned_evaluations = max(1, int(policy.get("repeats", 1) or 1)) + (
            1 if "composition" in policy.get("evaluator_modes", ()) else 0
        )
        if planned_evaluations > int(policy.get("cost_ceiling_units", 0) or 0):
            return {
                "schema_version": "lunar.mcp.quality-candidate-assessment/v1",
                "operation_role": "artifact_assessment",
                "control_traffic": True,
                "presentable_as_user_answer": False,
                "status": "inconclusive",
                "reason": "quality_assessment_inconclusive: evaluation budget insufficient",
                "evaluation_policy": policy,
                "assessment": None,
                "authorized_assessment": None,
                "execution_performed": False,
                "provider_call_performed": False,
            }
        artifact_runs = _run_configured_repetitions(
            adapter,
            "artifact_assessment",
            plan=plan,
            context=evaluation_context,
        )
        phase_runs = [artifact_runs]
        if "composition" in policy.get("evaluator_modes", ()):
            phase_runs.append(
                _run_configured_repetitions(
                    adapter,
                    "composition_assessment",
                    plan=plan,
                    context=evaluation_context,
                    required_repetitions=1,
                )
            )
        internal_adapter_used = True
        policy_evaluation_receipts = [
            dict(receipt)
            for phase in phase_runs
            for receipt in phase.get("receipts", ())
        ]
        expected_ids = {
            str(criterion["criterion_id"]) for criterion in plan.get("criteria", ())
        }
        reconciled_rows, reconciliation_error = _reconcile_criterion_results(
            phase_runs, expected_ids
        )
        if reconciliation_error:
            return {
                "schema_version": "lunar.mcp.quality-candidate-assessment/v1",
                "operation_role": "artifact_assessment",
                "control_traffic": True,
                "presentable_as_user_answer": False,
                "status": "inconclusive",
                "reason": f"quality_assessment_inconclusive: {reconciliation_error}",
                "policy_evaluation_receipts": policy_evaluation_receipts,
                "policy_reconciliation": [
                    dict(phase.get("reconciliation", {})) for phase in phase_runs
                ],
                "evaluation_policy": _evaluation_policy(plan),
                "assessment": None,
                "authorized_assessment": None,
                "execution_performed": False,
                "provider_call_performed": True,
            }
        rows = reconciled_rows or []
        try:
            _validate_internal_result_anchors(
                candidate_artifact, list(authorized_evidence or ()), rows
            )
        except ValueError as exc:
            return {
                "schema_version": "lunar.mcp.quality-candidate-assessment/v1",
                "operation_role": "artifact_assessment",
                "control_traffic": True,
                "presentable_as_user_answer": False,
                "status": "inconclusive",
                "reason": str(exc),
                "policy_evaluation_receipts": policy_evaluation_receipts,
                "assessment": None,
                "authorized_assessment": None,
                "execution_performed": False,
                "provider_call_performed": True,
            }
        evaluator = dict(adapter.identity)
        key = _trusted_attestation_key()
        authorization = issue_evaluator_authorization(
            plan,
            candidate_artifact,
            evaluator=evaluator,
            producer_id=producer_id,
            nonce=str(policy_evaluation_receipts[0].get("digest", "internal"))[-24:],
            trusted_key=key,
        )
        anchor_manifest = attest_anchor_manifest(
            authorization,
            artifact_anchors=[
                anchor for row in rows for anchor in row.get("artifact_anchors", ())
            ],
            source_anchors=[
                anchor for row in rows for anchor in row.get("source_anchors", ())
            ],
            trusted_key=key,
        )
        result_attestation = attest_evaluator_results(
            authorization, rows, anchor_manifest, trusted_key=key
        )
        trusted_by_id = {
            str(row.get("criterion_id")): dict(row)
            for row in (trusted_deterministic_results or ())
            if isinstance(row, Mapping) and row.get("criterion_id")
        }
        deterministic_receipts = [
            attest_deterministic_check(
                authorization,
                criterion_id=str(criterion["criterion_id"]),
                verdict=str(
                    trusted_by_id.get(str(criterion["criterion_id"]), {}).get(
                        "verdict", "inconclusive"
                    )
                ),
                artifact_anchors=trusted_by_id.get(
                    str(criterion["criterion_id"]), {}
                ).get("artifact_anchors", ()),
                source_anchors=trusted_by_id.get(
                    str(criterion["criterion_id"]), {}
                ).get("source_anchors", ()),
                verifier={
                    "id": "lunar-deterministic-contract-gate",
                    "configuration": (
                        "server-verified-delivery-v1"
                        if str(criterion["criterion_id"]) in trusted_by_id
                        else "unavailable-without-delivery-receipt-v1"
                    ),
                },
                trusted_key=key,
            )
            for criterion in plan.get("criteria", ())
            if criterion.get("evaluator_mode") in {"deterministic", "hybrid"}
        ]
    elif int(_evaluation_policy(plan).get("repeats", 1) or 1) > 1:
        return {
            "schema_version": "lunar.mcp.quality-candidate-assessment/v1",
            "operation_role": "artifact_assessment",
            "control_traffic": True,
            "presentable_as_user_answer": False,
            "status": "inconclusive",
            "reason": (
                "quality_assessment_inconclusive: external receipts do not carry "
                "the policy-required repeated/composition evaluations"
            ),
            "assessment": None,
            "authorized_assessment": None,
            "execution_performed": False,
            "provider_call_performed": False,
            "evaluation_policy": _evaluation_policy(plan),
        }
    if evaluator is None:
        raise ValueError("evaluator identity is required")
    if authorization is None or result_attestation is None or anchor_manifest is None:
        raise ValueError("authenticated evaluator receipts are required")
    authorized_assessment = assess_authorized_quality_artifact(
        plan,
        candidate_artifact,
        rows,
        evaluator=evaluator,
        producer_id=producer_id,
        authorization=authorization,
        result_attestation=result_attestation,
        deterministic_receipts=deterministic_receipts or [],
        anchor_manifest=anchor_manifest,
        trusted_key=_trusted_attestation_key(),
    )
    assessment = authorized_assessment["assessment"]
    require_valid_contract(assessment)
    summary = _quality_summary(plan, assessment=assessment)
    log, markdown = _reasoning_projection(plan, summary, assessment=assessment)
    return {
        "schema_version": "lunar.mcp.quality-candidate-assessment/v1",
        "operation_role": "artifact_assessment",
        "control_traffic": True,
        "presentable_as_user_answer": False,
        "assessment": assessment,
        "authorized_assessment": authorized_assessment,
        "quality_summary": summary,
        "reasoning_log": log,
        "reasoning_log_markdown": markdown,
        "execution_performed": False,
        "provider_call_performed": internal_adapter_used,
        "policy_evaluation_receipts": policy_evaluation_receipts,
        "evaluation_policy": _evaluation_policy(plan),
    }


def decide_quality_delivery_operation(
    plan: Mapping[str, Any],
    authorized_assessment: Mapping[str, Any],
    candidate_artifact: Any,
) -> dict[str, object]:
    """Release only the exact candidate admitted by the non-compensatory gate."""

    require_valid_contract(plan)
    assessment = authorized_assessment.get("assessment")
    if not isinstance(assessment, Mapping):
        raise ValueError("an authorized assessment package is required")
    require_valid_contract(assessment)
    decision = decide_authorized_final_delivery(
        plan,
        authorized_assessment,
        candidate_artifact,
        trusted_key=_trusted_attestation_key(),
    )
    require_valid_contract(decision)
    summary = _quality_summary(plan, assessment=assessment, decision=decision)
    log, markdown = _reasoning_projection(
        plan, summary, assessment=assessment, decision=decision
    )
    released = decision["decision"] == "release"
    return {
        "schema_version": "lunar.mcp.final-quality-delivery/v1",
        "operation_role": "final_delivery",
        "control_traffic": False,
        "presentable_as_user_answer": released,
        "decision": decision,
        "released_artifact": candidate_artifact if released else None,
        "candidate_withheld": not released,
        "repair": build_quality_repair(assessment) if not released else None,
        "quality_summary": summary,
        "reasoning_log": log,
        "reasoning_log_markdown": markdown,
        "execution_performed": False,
        "provider_call_performed": False,
    }
