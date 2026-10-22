# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0

"""Regression coverage for provenance-status corrections versus live refresh.

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
            "The report calls the connector output live, but all eight rows are "
            "deterministic fallbacks and there were zero live calls. Correct the "
            "provenance label and distinguish staged, cached, and retrieved evidence."
        ),
        (
            "This table is mislabeled as a fresh retrieval: its records are cached "
            "facts or staged queries and no live retrieval was executed. Audit the "
            "wording without network access."
        ),
        (
            "The manuscript says these results came from the portal. They did not: "
            "the rows are fallback-only. Make the provenance display faithful and "
            "do not call an external service."
        ),
    ],
)
def test_provenance_status_correction_routes_to_local_audit(command_text: str) -> None:
    """Verify provenance status correction routes to local audit."""
    retrieval, decision = _route(command_text)
    assert decision["selected"]["id"] == "methods-provenance-auditor"
    selected_row = next(
        row
        for row in retrieval["candidates"]
        if row["id"] == decision["selected"]["id"]
    )
    assert (
        preflight(
            decision["selected"],
            selected_row["contract"],
            {"denied_permissions": ["network"]},
        )["authority_status"]
        == "allowed"
    )

    candidate_ids = [row["id"] for row in retrieval["candidates"]]
    assert "claim-fidelity-verifier" in candidate_ids
    assert candidate_ids.index("claim-fidelity-verifier") > candidate_ids.index(
        "methods-provenance-auditor"
    )


@pytest.mark.parametrize(
    "command_text",
    [
        (
            "Run a current live evidence refresh across PubMed and GEO; record the "
            "query diagnostics, candidate exclusions, and no-hit rows."
        ),
        (
            "The report currently contains cached results. Perform a new external "
            "evidence refresh now and preserve the source, timestamp, screening, "
            "deduplication, and empty-query records."
        ),
    ],
)
def test_affirmative_refresh_request_still_routes_to_refresh_runner(
    command_text: str,
) -> None:
    """Verify affirmative refresh request still routes to refresh runner."""
    _retrieval, decision = _route(command_text)
    assert decision["selected"]["id"] == "live-evidence-refresh-runner"


def test_retrieval_receipt_explains_polarity_adjustment() -> None:
    """Verify retrieval receipt explains polarity adjustment."""
    candidates = _route(
        "The report falsely labels fallback rows as live results even though there "
        "were zero live calls. Audit and correct the provenance display."
    )[0]["candidates"]
    auditor = next(
        row for row in candidates if row["id"] == "methods-provenance-auditor"
    )

    assert auditor["semantic_score_adjustment"] > 0
    assert auditor["semantic_routing_reasons"] == [
        "existing-artifact provenance status and method labeling require an audit"
    ]
