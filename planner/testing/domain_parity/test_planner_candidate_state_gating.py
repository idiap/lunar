# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0

"""Candidate discoverability must remain separate from claim eligibility.

This module protects expected behavior for the corresponding workflow, script, or repository surface. Key concepts: regression coverage, interface stability, and output integrity.
"""

from __future__ import annotations

import pytest

from catalog.workflows.public.dependencies.planner import load_surface_index
from catalog.workflows.public.dependencies.planner.staged_routing import (
    _resolve_requirement_candidate,
    normalize_request,
    preflight,
)


def _route(command_text: str) -> tuple[dict, dict]:
    """Route."""
    retrieval, decision, _coverage = _resolve_requirement_candidate(
        command_text,
        normalize_request(command_text),
        load_surface_index(),
    )
    return retrieval, decision


@pytest.mark.parametrize(
    "command_text",
    [
        (
            "The latest report lists GSE317536 and GSE317349 in a way that could "
            "be read as incorporated evidence. They were only post-review GEO "
            "candidates. Show their review state and prevent them from influencing "
            "the manuscript until screening and claim gating are complete."
        ),
        (
            "These GEO accessions are candidates only. Keep them visible with their "
            "review status but do not let them support claims before screening and "
            "claim gating."
        ),
        (
            "Retain these pending-review datasets in the source register, label their "
            "status, and keep them out of conclusions until eligibility review is "
            "complete."
        ),
        (
            "The evidence list contains unreviewed external records. Preserve their "
            "discovery provenance while preventing manuscript influence until the "
            "directness gate passes."
        ),
    ],
)
def test_pending_candidates_route_to_claim_gate_without_execution(
    command_text: str,
) -> None:
    """Verify pending candidates route to claim gate without execution."""
    retrieval, decision = _route(command_text)

    assert decision["selected"]["id"] == "evidence-directness-claim-gater"
    candidates = retrieval["candidates"]
    ids = [row["id"] for row in candidates]
    assert ids[0] == "evidence-directness-claim-gater"
    assert "external-source-registry-builder" in ids[:3]
    assert "claim-fidelity-verifier" in ids
    selected_row = candidates[0]
    assert (
        preflight(
            decision["selected"], selected_row["contract"], {"mode": "planning_only"}
        )["authority_status"]
        == "allowed"
    )
    refresh = next(
        (row for row in candidates if row["id"] == "live-evidence-refresh-runner"),
        None,
    )
    assert refresh is None or refresh["semantic_score_adjustment"] < 0


def test_affirmative_candidate_screening_is_not_a_status_only_gate() -> None:
    """Verify affirmative candidate screening is not a status only gate."""
    _retrieval, decision = _route(
        "Screen and review these GEO candidates now against the inclusion criteria."
    )
    assert decision["selected"]["id"] != "evidence-directness-claim-gater"


def test_actual_live_refresh_remains_refresh_runner() -> None:
    """Verify actual live refresh remains refresh runner."""
    _retrieval, decision = _route(
        "Run a current live refresh of GEO for melanoma liver metastasis candidates."
    )
    assert decision["selected"]["id"] == "live-evidence-refresh-runner"


def test_pure_source_provenance_remains_methods_audit() -> None:
    """Verify pure source provenance remains methods audit."""
    _retrieval, decision = _route(
        "Audit the source lineage and retrieval timestamps for these GEO accessions."
    )
    assert decision["selected"]["id"] == "methods-provenance-auditor"


def test_explicit_promotion_is_not_misread_as_pending_candidate_gating() -> None:
    """Verify explicit promotion is not misread as pending candidate gating."""
    retrieval, decision = _route(
        "Promote these screened GEO datasets into the manuscript evidence base."
    )
    assert (decision.get("selected") or {}).get("id") != (
        "evidence-directness-claim-gater"
    )
    gate = next(
        (
            row
            for row in retrieval["candidates"]
            if row["id"] == "evidence-directness-claim-gater"
        ),
        None,
    )
    assert gate is None or gate["semantic_score_adjustment"] == 0
