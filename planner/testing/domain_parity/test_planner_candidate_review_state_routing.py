# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0

"""Candidate review-state and claim-influence routing regressions.

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


def _selected(text: str) -> tuple[str | None, dict]:
    """Selected."""
    retrieval, decision, _coverage = _resolve_requirement_candidate(
        text, normalize_request(text), load_surface_index()
    )
    return (decision.get("selected") or {}).get("id"), retrieval


@pytest.mark.parametrize(
    "text",
    [
        "The report lists GSE317536 and GSE317349 as incorporated evidence, but they are post-review GEO candidates. Show their review state and prevent manuscript influence until screening and claim gating complete.",
        "Mark these newly found records unreviewed in the evidence table and keep them out of conclusions until review and the claim gate pass.",
        "The manuscript citation list makes pending-screening candidates look admitted. Correct their status and do not let them support claims yet.",
        "Audit the report's candidate evidence labels: these records were not reviewed or incorporated, and conclusions must remain unchanged pending screening.",
    ],
)
def test_candidate_review_state_gate_routes_to_claim_gater(text: str) -> None:
    """Verify candidate review state gate routes to claim gater."""
    selected, retrieval = _selected(text)
    assert selected == "evidence-directness-claim-gater"
    gater = next(row for row in retrieval["candidates"] if row["id"] == selected)
    assert gater["semantic_score_adjustment"] >= 180


@pytest.mark.parametrize(
    "text",
    [
        "Polish the already reviewed melanoma manuscript for journal submission.",
        "Search GEO for new melanoma datasets and screen the returned records.",
        "Summarize the incorporated evidence without changing its review state.",
    ],
)
def test_non_candidate_gate_requests_do_not_receive_candidate_gate_boost(
    text: str,
) -> None:
    """Verify non candidate gate requests do not receive candidate gate boost."""
    _selected_id, retrieval = _selected(text)
    auditor = next(
        (
            row
            for row in retrieval["candidates"]
            if row["id"] == "methods-provenance-auditor"
        ),
        None,
    )
    if auditor is not None:
        assert not any(
            "candidate evidence review state" in reason
            for reason in auditor["semantic_routing_reasons"]
        )


@pytest.mark.parametrize(
    "text",
    [
        "For each melanoma-related statement, add a citation link resolving to the exact source record and show whether it came from an endpoint cohort, mouse model, review chapter, or unreviewed candidate.",
        "Map every claim to its exact source ID and label the evidence role beside the citation link.",
        "I need per-statement citation links to stable source records, with the source class visible for cohort, model, review, and candidate evidence.",
    ],
)
def test_statement_source_role_mapping_routes_to_citation_linker(text: str) -> None:
    """Verify statement source role mapping routes to citation linker."""
    selected, retrieval = _selected(text)
    assert selected == "citation-reference-linker"
    linker = next(row for row in retrieval["candidates"] if row["id"] == selected)
    assert linker["semantic_score_adjustment"] >= 180


@pytest.mark.parametrize(
    "text",
    [
        "Run a live evidence refresh and return newly retrieved melanoma records.",
        "Add one bibliography link for the report.",
    ],
)
def test_refresh_or_single_bibliography_request_is_not_statement_role_mapping(
    text: str,
) -> None:
    """Verify refresh or single bibliography request is not statement role mapping."""
    selected, _retrieval = _selected(text)
    assert selected != "citation-reference-linker"


@pytest.mark.parametrize(
    "text",
    [
        "The HTML report and manuscript disagree on mechanism versus endpoint context. Use one adjudicated claim state and detect drift before release.",
        "The brief and appendix have conflicting claim ceilings; verify one claim state across both outputs before release.",
        "Detect semantic claim drift between report, manuscript, and HTML while allowing their prose to differ.",
    ],
)
def test_cross_output_claim_drift_routes_to_fidelity_verifier(text: str) -> None:
    """Verify cross output claim drift routes to fidelity verifier."""
    selected, retrieval = _selected(text)
    assert selected == "claim-fidelity-verifier"
    verifier = next(row for row in retrieval["candidates"] if row["id"] == selected)
    assert verifier["semantic_score_adjustment"] >= 190


def test_single_surface_mechanism_edit_is_not_cross_output_drift() -> None:
    """Verify single surface mechanism edit is not cross output drift."""
    selected, _retrieval = _selected(
        "Polish the manuscript mechanism paragraph for readability."
    )
    assert selected != "claim-fidelity-verifier"


@pytest.mark.parametrize(
    "text",
    [
        "When the evidence refresh runs next quarter, show what changed in sources, claim ceilings, figures, and conclusions compared with this release, including demoted and unchanged items.",
        "After the next release, produce a release-to-release delta of promoted, demoted, unchanged, and unresolved report content.",
        "For the future refresh cycle, compare the successor report versus this immutable release and expose source and conclusion changes.",
    ],
)
def test_future_release_change_view_routes_to_version_comparator(text: str) -> None:
    """Verify future release change view routes to version comparator."""
    selected, retrieval = _selected(text)
    assert selected == "controlled-document-version-comparator"
    comparator = next(row for row in retrieval["candidates"] if row["id"] == selected)
    assert comparator["semantic_score_adjustment"] >= 200


def test_affirmative_live_refresh_still_routes_to_refresh() -> None:
    """Verify affirmative live refresh still routes to refresh."""
    selected, _retrieval = _selected(
        "Run the live evidence refresh now and retrieve current melanoma records."
    )
    assert selected == "live-evidence-refresh-runner"


@pytest.mark.parametrize(
    "text",
    [
        "Add a melanoma-only appendix organizing each source by liver-site definition, treatment, species, specimen, endpoint, and allowed use. Do not alter the cross-cancer main manuscript.",
        "Build a source-level appendix with treatment, specimen, endpoint, and allowed-use columns while preserving the main report.",
        "Create an appendix table per source for species, specimen, endpoint, and liver-site definition without changing the primary report.",
    ],
)
def test_structured_source_appendix_routes_to_appendix_describer(text: str) -> None:
    """Verify structured source appendix routes to appendix describer."""
    selected, retrieval = _selected(text)
    assert selected == "appendix-table-narrative-describer"
    appendix = next(row for row in retrieval["candidates"] if row["id"] == selected)
    assert appendix["semantic_score_adjustment"] >= 200


def test_model_translation_question_is_not_source_appendix() -> None:
    """Verify model translation question is not source appendix."""
    selected, _retrieval = _selected(
        "Assess whether this mouse model is relevant to human melanoma response."
    )
    assert selected == "preclinical-model-relevance-adjudicator"


def test_external_support_word_does_not_infer_network_permission() -> None:
    """Verify external support word does not infer network permission."""
    result = preflight(
        {"id": "contextual-causal-graph", "available": True},
        {
            "description": "Represent internal versus external support in a contextual graph.",
            "authority": {"permissions": []},
        },
        {"denied_permissions": ["network"]},
    )
    assert result["authority_status"] == "allowed"


def test_explicit_remote_api_operation_still_requires_network_permission() -> None:
    """Verify explicit remote API operation still requires network permission."""
    result = preflight(
        {"id": "remote-source", "available": True},
        {
            "description": "Query a remote API service for current records.",
            "authority": {"permissions": []},
        },
        {"denied_permissions": ["network"]},
    )
    assert result["authority_status"] == "denied"
