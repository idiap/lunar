# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Generic host-owned quality controls for selected package executions."""

from .quality import (
    quality_surface_inventory,
    review_quality_plan_operation,
    assess_quality_candidate_operation,
    decide_quality_delivery_operation,
)


def quality_surface_inventory_tool() -> dict[str, object]:
    """Inventory delivery and non-delivery MCP/plugin operations."""

    return quality_surface_inventory()


def review_quality_plan_tool(
    plan: dict[str, object],
    *,
    reviewer: dict[str, object] | None = None,
    independent: bool = False,
    semantic_review: dict[str, object] | None = None,
    criterion_producer_id: str | None = None,
    review_authorization: dict[str, object] | None = None,
    review_attestation: dict[str, object] | None = None,
) -> dict[str, object]:
    """Validate, review, and conditionally freeze a contextual quality plan."""

    return review_quality_plan_operation(
        plan,
        reviewer=reviewer,
        independent=independent,
        semantic_review=semantic_review,
        criterion_producer_id=criterion_producer_id,
        review_authorization=review_authorization,
        review_attestation=review_attestation,
    )


def assess_quality_candidate_tool(
    plan: dict[str, object],
    candidate_artifact: object,
    criterion_results: list[dict[str, object]] | None = None,
    *,
    evaluator: dict[str, object] | None = None,
    producer_id: str | None = None,
    authorization: dict[str, object] | None = None,
    result_attestation: dict[str, object] | None = None,
    deterministic_receipts: list[dict[str, object]] | None = None,
    anchor_manifest: dict[str, object] | None = None,
    authorized_evidence: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    """Record provider-neutral criterion results against one exact candidate."""

    return assess_quality_candidate_operation(
        plan,
        candidate_artifact,
        criterion_results,
        evaluator=evaluator,
        producer_id=producer_id,
        authorization=authorization,
        result_attestation=result_attestation,
        deterministic_receipts=deterministic_receipts,
        anchor_manifest=anchor_manifest,
        authorized_evidence=authorized_evidence,
    )


def assess_executed_quality_candidate_tool(
    plan: dict[str, object],
    candidate_artifact: object,
    *,
    producer_id: str | None,
    authorized_evidence: list[dict[str, object]],
    deterministic_results: list[dict[str, object]],
) -> dict[str, object]:
    """Assess a run with deterministic facts verified inside the MCP server."""

    return assess_quality_candidate_operation(
        plan,
        candidate_artifact,
        None,
        evaluator=None,
        producer_id=producer_id,
        authorization=None,
        result_attestation=None,
        deterministic_receipts=None,
        anchor_manifest=None,
        authorized_evidence=authorized_evidence,
        trusted_deterministic_results=deterministic_results,
    )


def decide_quality_delivery_tool(
    plan: dict[str, object],
    authorized_assessment: dict[str, object],
    candidate_artifact: object,
) -> dict[str, object]:
    """Issue a final decision and expose only an exactly assessed release artifact."""

    return decide_quality_delivery_operation(
        plan, authorized_assessment, candidate_artifact
    )
