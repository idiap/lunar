# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0

"""Tests for Capability profiles.

This module protects expected behavior for the corresponding workflow, script, or repository surface. Key concepts: regression coverage, interface stability, and output integrity.
"""

from __future__ import annotations

from pathlib import Path


from lunar_planner.capability_profiles import (
    load_capability_profiles,
    plan_profile_operations,
)


class CatalogRuntimeBindingRegistry:
    def resolve(self, logical_id, operation):
        return None


def test_catalog_registry_and_reviewed_profile_plan_one_bound_operation_end_to_end() -> (
    None
):
    """Verify catalog registry and reviewed profile plan one bound operation end to end."""
    path = Path(
        "catalog/contracts/capability-profiles/scientific/belief-revision-trace-compiler.json"
    )
    profiles = load_capability_profiles([path])
    skill_id = "scientific:belief-revision-trace-compiler"
    operation_id = "belief-revision-trace-compiler:compute"
    result = plan_profile_operations(
        skill_id,
        profiles[skill_id]["skill_digest"],
        profiles,
        CatalogRuntimeBindingRegistry(),
        operation_ids=[operation_id],
    )
    assert result["status"] == "ready"
    assert result["tasks"] == []
    assert (
        result["invocations"][0]["binding_id"]
        in profiles[skill_id]["operations"][0]["runtime_binding_ids"]
    )
    assert result["invocations"][0]["executed"] is False


def test_catalog_registry_and_reviewed_profile_plan_recovered_closure_assessor() -> (
    None
):
    """Verify catalog registry and reviewed profile plan recovered closure assessor."""
    path = Path(
        "catalog/contracts/capability-profiles/planner/closure-readiness-assessor.json"
    )
    profiles = load_capability_profiles([path])
    skill_id = "planner:closure-readiness-assessor"
    operation_id = "closure-readiness-assessor:compute"
    result = plan_profile_operations(
        skill_id,
        profiles[skill_id]["skill_digest"],
        profiles,
        CatalogRuntimeBindingRegistry(),
        operation_ids=[operation_id],
    )
    assert result["status"] == "ready"
    assert result["tasks"] == []
    assert result["invocations"][0]["operation_id"] == operation_id
    assert result["invocations"][0]["executed"] is False


def test_configured_host_attaches_reviewed_profiles_and_plans_real_unavailable_bindings() -> (
    None
):
    """Verify configured host attaches reviewed profiles and plans real unavailable bindings."""
    from lunar_planner import current_ports, plan_skill_operations
    from lunar_planner.config import configure, current_config
    from lunar_planner.ports import configure_ports, skill_descriptors
    from catalog.integrations.planner import configure_lunar_planner

    previous_ports = current_ports()
    previous_config = current_config()
    try:
        configure_lunar_planner()
        assert isinstance(
            current_ports().runtime_bindings, CatalogRuntimeBindingRegistry
        )
        descriptors = {row["id"]: row for row in skill_descriptors(("scientific",))}
        for skill_id in (
            "scientific:asco-publication-search",
            "scientific:counterfactual-reasoning",
        ):
            descriptor = descriptors[skill_id]
            assert descriptor["capability_profile_status"] == "reviewed"
            assert (
                descriptor["capability_profile"]["skill_digest"]
                == descriptor["content_digest"]
            )

        asco = plan_skill_operations(
            "scientific:asco-publication-search",
            operation_ids=["asco-publication-search:retrieve"],
        )
        assert asco["status"] == "blocked"
        assert (
            asco["tasks"][0]["binding_id"]
            == "binding.external-oncology-society-publications.v1"
        )
        assert asco["tasks"][0]["kind"] == "binding_unavailable"
    finally:
        configure_ports(previous_ports)
        configure(previous_config)
