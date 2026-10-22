# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0

"""Trusted assessment receipts for the contextual-quality release boundary.

Content addressing detects mutation; it does not establish who produced a
verdict.  This module adds HMAC-authenticated plan-review authorization,
semantic-review results, evaluator authorization, criterion results,
deterministic checks, and anchor manifests. The key belongs to the configured
Lunar evaluator adapter and is never accepted as an MCP argument.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Iterable, Mapping
from typing import Any

from .answer_trust import assess_answer_trust, resolve_answer_trust_rollout
from .workflow_economics import (
    build_workflow_cost_reconciliation,
    build_workflow_economics_report,
    build_workflow_resource_usage,
)
from .contracts import canonical_digest, seal_quality_contract, validate_contract
from .quality_attestation import verify_signed_quality_receipt
from .ports import ArtifactStore
from .staged_routing import assess_quality_artifact, decide_final_delivery


def _bytes(value: Mapping[str, Any]) -> bytes:
    """Bytes."""
    payload = {
        key: item for key, item in value.items() if key not in {"digest", "signature"}
    }
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()


def _sign(value: Mapping[str, Any], trusted_key: bytes) -> str:
    """Sign."""
    if len(trusted_key) < 32:
        raise ValueError("quality attestation key must contain at least 32 bytes")
    return (
        "hmac-sha256:"
        + hmac.new(trusted_key, _bytes(value), hashlib.sha256).hexdigest()
    )


def _seal_signed(value: Mapping[str, Any], trusted_key: bytes) -> dict[str, Any]:
    """Seal signed."""
    result = dict(value)
    result["signature"] = _sign(result, trusted_key)
    return seal_quality_contract(result)


def _verify(value: Mapping[str, Any], trusted_key: bytes, label: str) -> None:
    """Verify."""
    verify_signed_quality_receipt(value, trusted_key, label)


def issue_evaluator_authorization(
    plan: Mapping[str, Any],
    artifact: Any,
    *,
    evaluator: Mapping[str, Any],
    producer_id: str | None,
    nonce: str,
    trusted_key: bytes,
) -> dict[str, Any]:
    """Issue a one-plan, one-artifact, one-evaluator authorization."""

    return _seal_signed(
        {
            "schema_version": "lunar.planner.evaluator-authorization/v1",
            "authorization_id": f"authorization-{nonce}",
            "root_interaction_id": plan.get("root_interaction_id"),
            "principal": dict(plan.get("principal", {})),
            "quality_plan_digest": plan.get("digest"),
            "artifact_digest": canonical_digest({"artifact": artifact}),
            "evaluator": dict(evaluator),
            "producer_id": producer_id,
            "criterion_ids": [
                str(row["criterion_id"]) for row in plan.get("criteria", ())
            ],
            "nonce": nonce,
            "issued_by": "configured-bioagents-quality-adapter",
        },
        trusted_key,
    )


def issue_plan_review_authorization(
    plan: Mapping[str, Any],
    *,
    reviewer: Mapping[str, Any],
    criterion_producer_id: str,
    nonce: str,
    trusted_key: bytes,
) -> dict[str, Any]:
    """Authorize one reviewer to assess one exact provisional quality plan."""

    reviewer_id = str(reviewer.get("id", ""))
    if not reviewer_id or not criterion_producer_id:
        raise ValueError(
            "plan review authorization requires reviewer and producer identities"
        )
    if reviewer_id == criterion_producer_id:
        raise ValueError(
            "criterion producer cannot authorize itself as the independent reviewer"
        )
    return _seal_signed(
        {
            "schema_version": "lunar.planner.quality-plan-review-authorization/v1",
            "authorization_id": f"plan-review-authorization-{nonce}",
            "root_interaction_id": plan.get("root_interaction_id"),
            "principal": dict(plan.get("principal", {})),
            "quality_plan_digest": plan.get("digest"),
            "reviewer": dict(reviewer),
            "criterion_producer_id": criterion_producer_id,
            "nonce": nonce,
            "issued_by": "configured-bioagents-quality-adapter",
        },
        trusted_key,
    )


def attest_plan_review_result(
    authorization: Mapping[str, Any],
    semantic_review: Mapping[str, Any],
    *,
    trusted_key: bytes,
) -> dict[str, Any]:
    """Attest the exact semantic adequacy-review result bytes."""

    return _seal_signed(
        {
            "schema_version": "lunar.planner.quality-plan-review-attestation/v1",
            "authorization_digest": authorization.get("digest"),
            "semantic_review_digest": canonical_digest(
                {"semantic_review": dict(semantic_review)}
            ),
        },
        trusted_key,
    )


def verify_authorized_plan_review(
    plan: Mapping[str, Any],
    semantic_review: Mapping[str, Any],
    *,
    reviewer: Mapping[str, Any],
    criterion_producer_id: str,
    authorization: Mapping[str, Any],
    result_attestation: Mapping[str, Any],
    trusted_key: bytes,
) -> dict[str, Any]:
    """Verify identity, separation, and exact-result binding for plan review."""

    _verify(authorization, trusted_key, "plan review authorization")
    _verify(result_attestation, trusted_key, "plan review result attestation")
    reviewer_id = str(reviewer.get("id", ""))
    if authorization.get("quality_plan_digest") != plan.get("digest"):
        raise ValueError("plan review authorization binds a different quality plan")
    if authorization.get("principal") != plan.get("principal"):
        raise ValueError("plan review authorization principal mismatch")
    if authorization.get("reviewer") != reviewer:
        raise ValueError(
            "plan reviewer identity or configuration changed after authorization"
        )
    if authorization.get("criterion_producer_id") != criterion_producer_id:
        raise ValueError("criterion producer identity changed after authorization")
    if not reviewer_id or reviewer_id == criterion_producer_id:
        raise ValueError("plan review does not establish producer/reviewer separation")
    if result_attestation.get("authorization_digest") != authorization.get("digest"):
        raise ValueError(
            "plan review result attestation binds a different authorization"
        )
    expected_result_digest = canonical_digest(
        {"semantic_review": dict(semantic_review)}
    )
    if result_attestation.get("semantic_review_digest") != expected_result_digest:
        raise ValueError("semantic plan review differs from its attestation")
    if semantic_review.get("plan_digest") != plan.get("digest"):
        raise ValueError("semantic plan review binds a different quality plan")
    if semantic_review.get("reviewer_id") != reviewer_id:
        raise ValueError("semantic plan review reviewer mismatch")
    if semantic_review.get("independent") is not True:
        raise ValueError("semantic plan review is not independent")
    if semantic_review.get("verdict") not in {"pass", "fail", "inconclusive"}:
        raise ValueError("semantic plan review verdict is invalid")
    return _seal_signed(
        {
            "schema_version": "lunar.planner.authorized-quality-plan-review/v1",
            "quality_plan_digest": plan.get("digest"),
            "reviewer": dict(reviewer),
            "criterion_producer_id": criterion_producer_id,
            "semantic_review": dict(semantic_review),
            "authorization_digest": authorization.get("digest"),
            "result_attestation_digest": result_attestation.get("digest"),
        },
        trusted_key,
    )


def attest_anchor_manifest(
    authorization: Mapping[str, Any],
    *,
    artifact_anchors: Iterable[str],
    source_anchors: Iterable[str],
    trusted_key: bytes,
) -> dict[str, Any]:
    """Attest the finite anchors the evaluator is allowed to cite."""

    return _seal_signed(
        {
            "schema_version": "lunar.planner.quality-anchor-manifest/v1",
            "authorization_digest": authorization.get("digest"),
            "artifact_anchors": sorted(set(map(str, artifact_anchors))),
            "source_anchors": sorted(set(map(str, source_anchors))),
        },
        trusted_key,
    )


def attest_evaluator_results(
    authorization: Mapping[str, Any],
    criterion_results: Iterable[Mapping[str, Any]],
    anchor_manifest: Mapping[str, Any],
    *,
    trusted_key: bytes,
) -> dict[str, Any]:
    """Bind the configured evaluator's exact structured result bytes."""

    return _seal_signed(
        {
            "schema_version": "lunar.planner.evaluator-result-attestation/v1",
            "authorization_digest": authorization.get("digest"),
            "anchor_manifest_digest": anchor_manifest.get("digest"),
            "criterion_results_digest": canonical_digest(
                {"criterion_results": [dict(row) for row in criterion_results]}
            ),
        },
        trusted_key,
    )


def attest_deterministic_check(
    authorization: Mapping[str, Any],
    *,
    criterion_id: str,
    verdict: str,
    artifact_anchors: Iterable[str],
    source_anchors: Iterable[str],
    verifier: Mapping[str, Any],
    trusted_key: bytes,
) -> dict[str, Any]:
    """Create a typed, authenticated deterministic criterion receipt."""

    return _seal_signed(
        {
            "schema_version": "lunar.planner.deterministic-check-receipt/v1",
            "authorization_digest": authorization.get("digest"),
            "criterion_id": criterion_id,
            "verdict": verdict,
            "artifact_anchors": list(artifact_anchors),
            "source_anchors": list(source_anchors),
            "verifier": dict(verifier),
        },
        trusted_key,
    )


def assess_authorized_quality_artifact(
    plan: Mapping[str, Any],
    artifact: Any,
    criterion_results: Iterable[Mapping[str, Any]],
    *,
    evaluator: Mapping[str, Any],
    producer_id: str | None,
    authorization: Mapping[str, Any],
    result_attestation: Mapping[str, Any],
    deterministic_receipts: Iterable[Mapping[str, Any]],
    anchor_manifest: Mapping[str, Any],
    trusted_key: bytes,
) -> dict[str, Any]:
    """Assess only authenticated, exact-identity, anchor-resolved evidence."""

    rows = [dict(row) for row in criterion_results]
    _verify(authorization, trusted_key, "evaluator authorization")
    _verify(anchor_manifest, trusted_key, "anchor manifest")
    _verify(result_attestation, trusted_key, "evaluator result attestation")
    artifact_digest = canonical_digest({"artifact": artifact})
    expected_ids = [str(row["criterion_id"]) for row in plan.get("criteria", ())]
    if authorization.get("quality_plan_digest") != plan.get("digest"):
        raise ValueError("evaluator authorization binds a different quality plan")
    if authorization.get("artifact_digest") != artifact_digest:
        raise ValueError("evaluator authorization binds a different artifact")
    if authorization.get("principal") != plan.get("principal"):
        raise ValueError("evaluator authorization principal mismatch")
    if authorization.get("evaluator") != evaluator:
        raise ValueError(
            "evaluator identity or configuration changed after authorization"
        )
    if authorization.get("producer_id") != producer_id:
        raise ValueError("producer identity changed after authorization")
    if authorization.get("criterion_ids") != expected_ids:
        raise ValueError("evaluator authorization criterion coverage mismatch")
    if anchor_manifest.get("authorization_digest") != authorization.get("digest"):
        raise ValueError("anchor manifest binds a different authorization")
    if result_attestation.get("authorization_digest") != authorization.get("digest"):
        raise ValueError("result attestation binds a different authorization")
    if result_attestation.get("anchor_manifest_digest") != anchor_manifest.get(
        "digest"
    ):
        raise ValueError("result attestation binds a different anchor manifest")
    if result_attestation.get("criterion_results_digest") != canonical_digest(
        {"criterion_results": rows}
    ):
        raise ValueError("criterion results differ from the evaluator attestation")

    allowed_artifact = set(map(str, anchor_manifest.get("artifact_anchors", ())))
    allowed_source = set(map(str, anchor_manifest.get("source_anchors", ())))
    for row in rows:
        if not set(map(str, row.get("artifact_anchors", ()))) <= allowed_artifact:
            raise ValueError("criterion result contains an unresolved artifact anchor")
        if not set(map(str, row.get("source_anchors", ()))) <= allowed_source:
            raise ValueError("criterion result contains an unresolved source anchor")

    receipt_by_id: dict[str, Mapping[str, Any]] = {}
    receipt_digests: list[str] = []
    for receipt in deterministic_receipts:
        _verify(receipt, trusted_key, "deterministic check receipt")
        if receipt.get("authorization_digest") != authorization.get("digest"):
            raise ValueError(
                "deterministic check receipt binds a different authorization"
            )
        criterion_id = str(receipt.get("criterion_id"))
        if criterion_id in receipt_by_id:
            raise ValueError("duplicate deterministic check receipt")
        receipt_by_id[criterion_id] = receipt
        receipt_digests.append(str(receipt["digest"]))
    criteria = {str(row["criterion_id"]): row for row in plan.get("criteria", ())}
    required_deterministic = {
        criterion_id
        for criterion_id, criterion in criteria.items()
        if criterion.get("evaluator_mode") in {"deterministic", "hybrid"}
    }
    if required_deterministic - set(receipt_by_id):
        raise ValueError("missing authenticated deterministic check receipt")
    for criterion_id in required_deterministic:
        receipt = receipt_by_id[criterion_id]
        if receipt.get("verdict") != "pass":
            matching = next(
                row for row in rows if str(row.get("criterion_id")) == criterion_id
            )
            matching["verdict"] = str(receipt.get("verdict", "inconclusive"))
        if not set(map(str, receipt.get("artifact_anchors", ()))) <= allowed_artifact:
            raise ValueError(
                "deterministic receipt contains an unresolved artifact anchor"
            )
        if not set(map(str, receipt.get("source_anchors", ()))) <= allowed_source:
            raise ValueError(
                "deterministic receipt contains an unresolved source anchor"
            )

    assessment = assess_quality_artifact(
        plan,
        artifact,
        rows,
        evaluator=evaluator,
        producer_id=producer_id,
    )
    package = _seal_signed(
        {
            "schema_version": "lunar.planner.authorized-quality-assessment/v1",
            "assessment": assessment,
            "authorization_digest": authorization["digest"],
            "result_attestation_digest": result_attestation["digest"],
            "anchor_manifest_digest": anchor_manifest["digest"],
            "deterministic_receipt_digests": sorted(receipt_digests),
        },
        trusted_key,
    )
    return package


def decide_authorized_final_delivery(
    plan: Mapping[str, Any],
    authorized_assessment: Mapping[str, Any],
    artifact: Any,
    *,
    trusted_key: bytes,
    authorized_trust_assessment: Mapping[str, Any] | None = None,
    accepted_trust_bands: Iterable[str] = ("high_control", "substantiated"),
    answer_trust_rollout_state: str = "off",
    answer_trust_promotion_metrics: Mapping[str, float | int] | None = None,
) -> dict[str, Any]:
    """Release only assessments admitted through trusted evidence paths.

    Answer trust is opt-in.  When supplied it may narrow the quality decision;
    it can never turn an existing revise or inconclusive decision into release.
    """

    _verify(authorized_assessment, trusted_key, "authorized assessment")
    assessment = authorized_assessment.get("assessment")
    if not isinstance(assessment, Mapping) or not validate_contract(assessment).valid:
        raise ValueError(
            "authorized assessment contains an invalid assessment contract"
        )
    decision = decide_final_delivery(plan, assessment, artifact)
    if authorized_trust_assessment is None:
        return decision
    rollout = resolve_answer_trust_rollout(
        answer_trust_rollout_state,
        promotion_metrics=answer_trust_promotion_metrics,
    )
    _verify(
        authorized_trust_assessment,
        trusted_key,
        "authorized answer trust assessment",
    )
    trust = authorized_trust_assessment.get("assessment")
    if not isinstance(trust, Mapping) or not validate_contract(trust).valid:
        raise ValueError(
            "authorized answer trust package contains an invalid assessment"
        )
    if trust.get("answer_digest") != canonical_digest(artifact):
        raise ValueError("answer trust assessment binds a different exact artifact")
    accepted = set(map(str, accepted_trust_bands))
    trust_passes = (
        trust.get("status") == "assessed"
        and trust.get("band") in accepted
        and not trust.get("blocking_reasons")
    )
    if (
        not rollout["release_effect_enabled"]
        or trust_passes
        or decision["decision"] != "release"
    ):
        return decision
    narrowed = dict(decision)
    narrowed["decision"] = (
        "revise" if trust.get("status") == "blocked" else "inconclusive"
    )
    narrowed["reasons"] = [
        *decision.get("reasons", ()),
        (
            "answer trust gate did not pass: "
            f"assessment={authorized_trust_assessment.get('digest')} "
            f"status={trust.get('status')} band={trust.get('band')}"
        ),
    ]
    narrowed["next_action"] = (
        "repair the weakest answer claim or supply the missing authorized "
        "evidence, lineage, preservation, or review receipt"
    )
    narrowed["presentable_as_user_answer"] = False
    return seal_quality_contract(narrowed)


def issue_answer_trust_authorization(
    answer: Mapping[str, Any],
    claims: Iterable[Mapping[str, Any]],
    evidence_atoms: Iterable[Mapping[str, Any]],
    derivation_edges: Iterable[Mapping[str, Any]],
    *,
    authorized_quality_assessment: Mapping[str, Any],
    provenance_reconciliation: Mapping[str, Any],
    generative_receipts: Iterable[Mapping[str, Any]] = (),
    computation_receipts: Iterable[Mapping[str, Any]] = (),
    human_reviews: Iterable[Mapping[str, Any]] = (),
    policy_digest: str,
    nonce: str,
    trusted_key: bytes,
) -> dict[str, Any]:
    """Authorize deterministic trust assessment over exact observed inputs."""

    _verify(authorized_quality_assessment, trusted_key, "authorized assessment")
    if answer.get("digest") != canonical_digest(answer):
        raise ValueError("answer digest is absent or non-canonical")
    rows = {
        "claims": [dict(row) for row in claims],
        "evidence_atoms": [dict(row) for row in evidence_atoms],
        "derivation_edges": [dict(row) for row in derivation_edges],
        "generative_receipts": [dict(row) for row in generative_receipts],
        "computation_receipts": [dict(row) for row in computation_receipts],
        "human_reviews": [dict(row) for row in human_reviews],
    }
    return _seal_signed(
        {
            "schema_version": "lunar.planner.answer-trust-authorization/v1",
            "authorization_id": f"answer-trust-authorization-{nonce}",
            "answer_digest": answer["digest"],
            "input_digests": {
                key: canonical_digest({key: value}) for key, value in rows.items()
            },
            "authorized_quality_assessment_digest": authorized_quality_assessment[
                "digest"
            ],
            "provenance_reconciliation_digest": canonical_digest(
                {"provenance_reconciliation": dict(provenance_reconciliation)}
            ),
            "policy_digest": str(policy_digest),
            "scorer": {
                "id": "bioagents-answer-trust",
                "version": "v1",
                "deterministic": True,
            },
            "nonce": str(nonce),
            "issued_by": "configured-bioagents-quality-adapter",
        },
        trusted_key,
    )


def assess_authorized_answer_trust(
    answer: Mapping[str, Any],
    claims: Iterable[Mapping[str, Any]],
    evidence_atoms: Iterable[Mapping[str, Any]],
    derivation_edges: Iterable[Mapping[str, Any]],
    *,
    authorization: Mapping[str, Any],
    authorized_quality_assessment: Mapping[str, Any],
    provenance_reconciliation: Mapping[str, Any],
    generative_receipts: Iterable[Mapping[str, Any]] = (),
    computation_receipts: Iterable[Mapping[str, Any]] = (),
    human_reviews: Iterable[Mapping[str, Any]] = (),
    policy: Mapping[str, Any] | None = None,
    trusted_key: bytes,
) -> dict[str, Any]:
    """Assess trust only after authorization binds every retrospective input."""

    _verify(authorization, trusted_key, "answer trust authorization")
    _verify(authorized_quality_assessment, trusted_key, "authorized assessment")
    rows = {
        "claims": [dict(row) for row in claims],
        "evidence_atoms": [dict(row) for row in evidence_atoms],
        "derivation_edges": [dict(row) for row in derivation_edges],
        "generative_receipts": [dict(row) for row in generative_receipts],
        "computation_receipts": [dict(row) for row in computation_receipts],
        "human_reviews": [dict(row) for row in human_reviews],
    }
    if authorization.get("answer_digest") != answer.get("digest"):
        raise ValueError("answer trust authorization binds a different answer")
    expected_inputs = {
        key: canonical_digest({key: value}) for key, value in rows.items()
    }
    if authorization.get("input_digests") != expected_inputs:
        raise ValueError("answer trust inputs changed after authorization")
    if authorization.get(
        "authorized_quality_assessment_digest"
    ) != authorized_quality_assessment.get("digest"):
        raise ValueError(
            "answer trust authorization binds a different quality assessment"
        )
    provenance_digest = canonical_digest(
        {"provenance_reconciliation": dict(provenance_reconciliation)}
    )
    if authorization.get("provenance_reconciliation_digest") != provenance_digest:
        raise ValueError("provenance reconciliation changed after authorization")
    quality = authorized_quality_assessment.get("assessment")
    if not isinstance(quality, Mapping) or not validate_contract(quality).valid:
        raise ValueError("authorized quality package contains an invalid assessment")
    assessment = assess_answer_trust(
        answer,
        rows["claims"],
        rows["evidence_atoms"],
        rows["derivation_edges"],
        generative_receipts=rows["generative_receipts"],
        computation_receipts=rows["computation_receipts"],
        provenance_reconciliation=provenance_reconciliation,
        quality_assessment=quality,
        human_reviews=rows["human_reviews"],
        scoring_policy_digest=str(authorization.get("policy_digest")),
        policy=policy,
    )
    if not validate_contract(assessment).valid:
        raise ValueError("answer trust scorer produced an invalid assessment contract")
    return _seal_signed(
        {
            "schema_version": "lunar.planner.authorized-answer-trust-assessment/v1",
            "authorization_digest": authorization["digest"],
            "assessment": assessment,
        },
        trusted_key,
    )


def persist_authorized_answer_trust(
    authorized_trust_assessment: Mapping[str, Any],
    *,
    plan_id: str,
    artifact_store: ArtifactStore,
    trusted_key: bytes,
) -> Mapping[str, Any]:
    """Persist one verified assessment through an explicit host artifact port."""

    _verify(
        authorized_trust_assessment,
        trusted_key,
        "authorized answer trust assessment",
    )
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", str(plan_id)):
        raise ValueError("unsafe planner plan_id for answer trust persistence")
    assessment = authorized_trust_assessment.get("assessment")
    if not isinstance(assessment, Mapping) or not validate_contract(assessment).valid:
        raise ValueError("cannot persist an invalid answer trust assessment")
    suffix = str(assessment["digest"]).split(":", 1)[-1]
    logical_id = (
        f"artifacts/runs/planner/{plan_id}/" f"answer-trust-assessment-{suffix}.json"
    )
    payload = (
        json.dumps(
            authorized_trust_assessment,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        )
        + "\n"
    ).encode("utf-8")
    return artifact_store.write(logical_id, payload)


def issue_workflow_economics_authorization(
    effort_artifact: Mapping[str, Any],
    resource_estimate: Mapping[str, Any],
    normalized_usage_receipts: Iterable[Mapping[str, Any]],
    *,
    plan_digest: str,
    comparator_digest: str,
    workload_inventory_digest: str,
    price_book_digest: str | None,
    nonce: str,
    trusted_key: bytes,
) -> dict[str, Any]:
    """Authorize retrospective economics over exact privacy-filtered inputs."""

    receipts = [dict(row) for row in normalized_usage_receipts]
    return _seal_signed(
        {
            "schema_version": "lunar.planner.workflow-economics-authorization/v1",
            "authorization_id": f"workflow-economics-authorization-{nonce}",
            "plan_digest": str(plan_digest),
            "comparator_digest": str(comparator_digest),
            "workload_inventory_digest": str(workload_inventory_digest),
            "effort_artifact_digest": canonical_digest(effort_artifact),
            "resource_estimate_digest": canonical_digest(resource_estimate),
            "usage_receipts_digest": canonical_digest({"usage_receipts": receipts}),
            "price_book_digest": price_book_digest,
            "polarity": "observed_only",
            "nonce": str(nonce),
            "issued_by": "configured-bioagents-quality-adapter",
        },
        trusted_key,
    )


def assess_authorized_workflow_economics(
    effort_artifact: Mapping[str, Any],
    resource_estimate: Mapping[str, Any],
    normalized_usage_receipts: Iterable[Mapping[str, Any]],
    priced_usage: Mapping[str, Any],
    *,
    authorization: Mapping[str, Any],
    trusted_key: bytes,
    reservation_digest: str | None = None,
    invoice_digest: str | None = None,
) -> dict[str, Any]:
    """Build a signed observed economics package after exact-input checks."""

    _verify(authorization, trusted_key, "workflow economics authorization")
    receipts = [dict(row) for row in normalized_usage_receipts]
    expected = {
        "effort_artifact_digest": canonical_digest(effort_artifact),
        "resource_estimate_digest": canonical_digest(resource_estimate),
        "usage_receipts_digest": canonical_digest({"usage_receipts": receipts}),
    }
    for field, value in expected.items():
        if authorization.get(field) != value:
            raise ValueError(f"workflow economics {field} changed after authorization")
    if authorization.get("price_book_digest") != priced_usage.get("price_book_digest"):
        raise ValueError("workflow economics price book changed after authorization")
    usage = build_workflow_resource_usage(str(authorization["plan_digest"]), receipts)
    cost = build_workflow_cost_reconciliation(
        usage,
        priced_usage,
        reservation_digest=reservation_digest,
        invoice_digest=invoice_digest,
    )
    report = build_workflow_economics_report(
        effort_artifact,
        usage,
        cost=cost,
        rollout_state="audit",
    )
    return _seal_signed(
        {
            "schema_version": "lunar.planner.authorized-workflow-economics/v1",
            "authorization_digest": authorization["digest"],
            "effort": dict(effort_artifact),
            "resource_usage": usage,
            "cost_reconciliation": cost,
            "report": report,
        },
        trusted_key,
    )


def persist_authorized_workflow_economics(
    authorized_economics: Mapping[str, Any],
    *,
    plan_id: str,
    artifact_store: ArtifactStore,
    trusted_key: bytes,
) -> Mapping[str, Any]:
    """Persist one verified economics package through an explicit host port."""

    _verify(authorized_economics, trusted_key, "authorized workflow economics")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", str(plan_id)):
        raise ValueError("unsafe planner plan_id for workflow economics persistence")
    report = authorized_economics.get("report")
    if (
        not isinstance(report, Mapping)
        or report.get("schema_version") != "lunar.planner.workflow-economics-report/v1"
    ):
        raise ValueError("cannot persist an invalid workflow economics package")
    suffix = str(report.get("digest", canonical_digest(report))).split(":", 1)[-1]
    logical_id = (
        f"artifacts/runs/planner/{plan_id}/workflow-economics/"
        f"economics-report-{suffix}.json"
    )
    payload = (
        json.dumps(authorized_economics, indent=2, sort_keys=True, ensure_ascii=False)
        + "\n"
    ).encode("utf-8")
    return artifact_store.write(logical_id, payload)
