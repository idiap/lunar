# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Standalone regression oracles for the extracted BioAgents domain contracts."""

from __future__ import annotations
import json
from pathlib import Path
from catalog.integrations.domain_package.runtime.config import paths
from catalog.integrations.domain_package.planning.runtime_preflight import (
    check_provider,
)
from catalog.integrations.domain_package.planning.biomni import plan_biomni_invocation
from catalog.integrations.domain_package.planning.provider_families import (
    compatibility,
    portfolio_priority_table,
    select_provider_family,
    validate_provider_document,
)
from catalog.integrations.domain_package.planning.wrapper_portfolio import (
    validate_wrapper_portfolio,
)

ROOT = paths().root


def test_portfolio_is_valid_complete_and_contains_both_waves() -> None:
    """Verify portfolio is valid complete and contains both waves."""
    path = ROOT / "catalog/integrations/external-frameworks/wrapper-portfolio.json"
    assert validate_wrapper_portfolio(path) == ()
    assert validate_wrapper_portfolio(path, repo_root=ROOT, strict=True) == ()
    table = portfolio_priority_table(path)
    ids = {row["skill_id"] for row in table}
    assert "single-cell-analysis-runtime" in ids
    assert "molecular-construct-verification" in ids
    assert {row["wave"] for row in table} >= {1, 2}


def test_three_valued_compatibility_rejects_unknown_and_lossy_conversion() -> None:
    """Verify three valued compatibility rejects unknown and lossy conversion."""
    required = {
        "type": "expression_matrix",
        "format": "SingleCellExperiment",
        "namespace": "Ensembl",
    }
    assert compatibility(required, {"type": "expression_matrix"})["status"] == "unknown"
    assert (
        compatibility(required, {"type": "variant_table", "format": "VCF"})["status"]
        == "incompatible"
    )
    lossy = compatibility(
        required,
        {
            "type": "expression_matrix",
            "format": "AnnData",
            "conversion_to": "SingleCellExperiment",
            "lossy_conversion": True,
        },
    )
    assert lossy["status"] == "unknown"


def test_preflight_is_non_executing_and_capability_specific(tmp_path: Path) -> None:
    """Verify preflight is non executing and capability specific."""
    ready = check_provider(
        "fixture:json", [{"kind": "python_package", "name": "json", "module": "json"}]
    )
    missing = check_provider(
        "fixture:missing",
        [{"kind": "command", "name": "bioagents-command-that-does-not-exist"}],
    )
    windows_path = check_provider(
        "fixture:windows",
        [
            {
                "kind": "local_checkout",
                "name": "checkout",
                "path": r"C:\BioAgents\provider",
            }
        ],
    )
    assert ready["readiness"] == "ready"
    assert missing["readiness"] == windows_path["readiness"] == "blocked"
    assert all(
        not report["executed"] and not report["installed"]
        for report in (ready, missing, windows_path)
    )


def test_biomni_missing_checkout_is_blocked_with_alternative(tmp_path: Path) -> None:
    """Verify Biomni missing checkout is blocked with alternative."""
    plan = plan_biomni_invocation(
        "query_geo",
        {"query": "melanoma liver metastasis"},
        checkout=tmp_path / "missing-biomni",
        capability_policy={"licence_status": "unknown"},
    )
    assert plan["status"] == "blocked"
    assert plan["executed"] is False
    assert plan["alternative_provider_plan"]["required"] is True
    assert plan["source_revision"] == "400c1f366b96a35ca253e13c9b06c5076af41d65"


def test_provider_result_schema_requires_w3c_provenance_links() -> None:
    """Verify provider result schema requires w3c provenance links."""
    invalid = {
        "schema_version": "bioagents.provider-result/v1",
        "provider_id": "fixture:test",
        "status": "completed",
        "outputs": {},
        "provider_receipt": {},
        "reasoning_events": [],
        "provenance": {"entity": "urn:e", "activity": "urn:a", "agent": "urn:g"},
    }
    assert validate_provider_document(invalid)


def test_planner_family_probes_bridge_the_lexical_gap() -> None:
    """Verify planner family probes bridge the lexical gap."""
    assert (
        select_provider_family(
            "Separate treatment-responsive immune states from donor effects in this sparse cell-by-gene object"
        )["selected_family"]
        == "single-cell-analysis-runtime"
    )
    assert (
        select_provider_family(
            "I have integer transcript counts and need the treatment coefficient while accounting for batch"
        )["selected_family"]
        == "bulk-transcriptomics-analysis"
    )


def test_typed_provider_filtering_rejects_incompatible_ports() -> None:
    """Verify typed provider filtering rejects incompatible ports."""
    plan = select_provider_family(
        "Estimate the treatment coefficient from this integer transcript count matrix",
        required_ports=({"type": "bulk_expression", "format": "integer_counts"},),
        provider_capabilities={
            "bioconductor:DESeq2": {
                "offers": ({"type": "variant_table", "format": "VCF"},),
                "requirements": ({"kind": "command", "name": "Rscript"},),
            }
        },
    )
    provider = next(
        row for row in plan["providers"] if row["provider_id"] == "bioconductor:DESeq2"
    )
    assert provider["compatibility"] == "incompatible"
    assert provider["disposition"] == "rejected"
    assert provider["preflight"]["operation"] == "check"


def test_blocked_family_returns_structured_gap_and_fallback() -> None:
    """Verify blocked family returns structured gap and fallback."""
    portfolio = json.loads(
        (
            ROOT / "catalog/integrations/external-frameworks/wrapper-portfolio.json"
        ).read_text()
    )
    plan = select_provider_family(
        "Decode these .fcs acquisitions and validate compensation against detector channels",
        portfolio=portfolio,
    )
    assert plan["status"] == "blocked"
    assert plan["skill_gap"]["family"] == "flow-cytometry-ingestion"
    assert plan["fallback_plan"]["status"] == "required"
    assert plan["selected_provider"] is None
