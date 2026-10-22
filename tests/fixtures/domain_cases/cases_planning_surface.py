# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Domain routing preserves its reviewed contracts without the portable planner."""

from catalog.integrations.domain_package.runtime.config import paths
from catalog.integrations.domain_package.planning.surface import build_surface_index
from catalog.integrations.domain_package.planning.bioconductor import (
    compile_package_relevance,
)
from catalog.integrations.domain_package.planning.report_inheritance import (
    build_report_workflow_inheritance,
)
from catalog.integrations.domain_package.planning.external_sources import (
    build_external_source_plan,
)
from catalog.integrations.domain_package.planning.routing_policy import (
    _semantic_retrieval_adjustment,
)


def test_surface_and_report_control_inheritance():
    """Verify surface and report control inheritance."""
    surface = build_surface_index(paths().root)
    assert surface["counts"]["skills"] == 694
    assert {row["scope"] for row in surface["skills"]} == {"scientific"}
    inheritance = build_report_workflow_inheritance(
        "Write a complex scientific paper from a completed workflow run with section-by-section critiques",
        surface,
    )
    assert inheritance["status"] == "incomplete_candidate"
    assert len(inheritance["mandatory_control_bindings"]) >= 15
    assert not inheritance["missing_source_workflow_ids"]
    assert inheritance["missing_mandatory_control_ids"] == [
        "skill-reuse-critical-reasoner"
    ]
    assert all(
        not row["weakening_allowed"] for row in inheritance["adaptation_decisions"]
    )


def test_typed_package_relevance_and_negation():
    """Verify typed package relevance and negation."""
    selected = compile_package_relevance(
        "Bring the H5AD objects into an R assay container and retain reductions and annotations."
    )
    assert selected["disposition"] == "selected"
    excluded = compile_package_relevance(
        "Keep this Scanpy workflow Python-native and do not use Bioconductor."
    )
    assert excluded["disposition"] == "considered_not_selected"
    assert excluded["reason"] == "explicit Bioconductor negation"


def test_external_source_plan_has_no_execution_authority():
    """Verify external source plan has no execution authority."""
    result = build_external_source_plan("Find recent melanoma literature")
    assert result["data_needs"]
    assert result["zero_io"] == {
        "network": False,
        "installation": False,
        "mutation": False,
    }
    assert result["access_budget_summary"]["requests"] == 0


def test_provenance_correction_does_not_request_live_refresh():
    """Verify provenance correction does not request live refresh."""
    frame = {
        "goal": "Correct the report wording: it claims live retrieval, but there were zero live calls and only cached results."
    }
    assert _semantic_retrieval_adjustment(frame, "live-evidence-refresh-runner")[0] < 0
    assert _semantic_retrieval_adjustment(frame, "methods-provenance-auditor")[0] > 0


def test_runtime_roots_do_not_search_host_ancestors(tmp_path):
    """Verify runtime roots do not search host ancestors."""
    import pytest
    from catalog.runtime.causal_agents._paths import repository_root as causal_root
    from catalog.runtime.upstream_skill_runtime import (
        repository_root,
        UpstreamRuntimeUnavailable,
    )

    assert causal_root() == paths().root
    assert repository_root(paths().root / "catalog/agents") == paths().root
    with pytest.raises(UpstreamRuntimeUnavailable, match="outside"):
        repository_root(tmp_path)
    with pytest.raises(RuntimeError, match="outside"):
        causal_root(tmp_path)
