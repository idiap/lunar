# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Standalone regression oracles for the extracted BioAgents domain contracts."""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

import pytest
from pydantic import ValidationError

from catalog.integrations.domain_package.runtime.adapters import (
    ADAPTERS,
    REPO_ROOT,
    public_workflow_ids,
    validate_run_request,
)
from catalog.integrations.domain_package.runtime.schemas import PrismRunRequest

MODEL_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")
EXPECTED_WORKFLOWS = {
    "drug-repurposing-coherence",
    "her2-arm-proteogenomics",
    "her2-biomarker-triage",
    "liver-metastasis-ecosystem",
    "lmdln-prioritization",
    "melanoma-resistance",
    "pharmaceutical-process-capture",
    "pharmaceutical-process-clone",
    "pharmaceutical-process-deviation",
    "plasma-multiomics",
    "resistance-circuits",
    "serial-ctdna",
    "serial-ctdna-causal",
}


def test_adapter_allowlist_matches_public_prism_bundle_exactly() -> None:
    """Verify adapter allowlist matches public prism bundle exactly."""
    assert set(ADAPTERS) == EXPECTED_WORKFLOWS
    assert public_workflow_ids() == {
        "biomedical-research-ethics",
        "biostatistical-experimental-design",
        "drug-repurposing-coherence",
        "liver-metastasis-ecosystem",
        "melanoma-resistance",
        "pharmaceutical-process",
        "resistance-circuits",
        "workflow-methodology-description",
    }


def test_adapter_sources_and_runtime_stages_are_reviewed() -> None:
    """Verify adapter sources and runtime stages are reviewed."""
    index = json.loads(
        (REPO_ROOT / "catalog" / "data_sources" / "index.json").read_text()
    )
    catalog_ids = {row["resource_id"] for row in index["resources"]}
    for adapter in ADAPTERS.values():
        assert {
            binding.resource_id for binding in adapter.source_bindings
        } <= catalog_ids
        assert len({stage.stage_id for stage in adapter.stages}) == len(adapter.stages)
        # Executable adapters include private projects and fixed operations absent
        # from the public browsing bundle; check their authored reasoning nodes.
        nodes = {
            name
            for source in adapter.prism_project.glob("*.prism")
            for name in re.findall(
                r"\[\s*([a-zA-Z_][a-zA-Z_0-9]*)\s*:", source.read_text()
            )
        }
        assert nodes
        assert all(
            stage.component_id.startswith("adapter-only:")
            or stage.component_id in nodes
            for stage in adapter.stages
        )


def test_study_accessions_bind_to_geo_with_distinct_roles() -> None:
    """Verify study accessions bind to geo with distinct roles."""
    melanoma = ADAPTERS["melanoma-resistance"]
    required = [binding for binding in melanoma.source_bindings if binding.required]
    assert [(item.resource_id, item.local_identifier) for item in required] == [
        ("gene-expression-omnibus-geo", "GSE120575"),
        ("gene-expression-omnibus-geo", "GSE91061"),
    ]
    circuits = [
        binding
        for binding in ADAPTERS["resistance-circuits"].source_bindings
        if binding.required
    ]
    assert [dict(item.metadata)["cohort_role"] for item in circuits] == [
        "PDAC-anchor",
        "HGSOC-transfer",
    ]


def test_adapter_validation_rejects_unknown_workflows_paths_and_network_authority() -> (
    None
):
    """Verify adapter validation rejects unknown workflows, paths, and network authority."""
    with pytest.raises(KeyError):
        validate_run_request("private-workflow", PrismRunRequest(ai_model_id=MODEL_ID))
    with pytest.raises(ValueError, match="outside"):
        validate_run_request(
            "melanoma-resistance",
            PrismRunRequest(
                ai_model_id=MODEL_ID, inputs={"data_root": "/tmp/unreviewed"}
            ),
        )
    with pytest.raises(PermissionError, match="network authority"):
        validate_run_request(
            "melanoma-resistance",
            PrismRunRequest(ai_model_id=MODEL_ID, network_authority=True),
        )
    with pytest.raises(ValidationError):
        validate_run_request(
            "pharmaceutical-process-capture",
            PrismRunRequest(
                ai_model_id=MODEL_ID,
                inputs={
                    "input_path": str(Path(__file__)),
                    "reference_workflow_id": "protein-a-capture-development",
                },
            ),
        )


def test_each_adapter_exposes_one_reasoning_output() -> None:
    """Verify each adapter exposes one reasoning output."""
    assert len({adapter.output_key for adapter in ADAPTERS.values()}) == 13
    assert all(
        adapter.output_key.endswith("_reasoning") for adapter in ADAPTERS.values()
    )


def test_pharmaceutical_cards_inject_one_fixed_operation() -> None:
    """Verify pharmaceutical cards inject one fixed operation."""
    expected = {
        "pharmaceutical-process-clone": "mab-clone-to-fed-batch-strategy",
        "pharmaceutical-process-capture": "protein-a-capture-development",
        "pharmaceutical-process-deviation": "pharmaceutical-batch-deviation-investigation",
    }
    for workflow_id, operation in expected.items():
        adapter, inputs = validate_run_request(
            workflow_id, PrismRunRequest(ai_model_id=MODEL_ID)
        )
        assert adapter.fixed_operation == inputs["reference_workflow_id"] == operation
