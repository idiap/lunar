# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0

"""Semantic and portable-schema tests for the planning-only contract layer.

This module protects expected behavior for the corresponding workflow, script, or repository surface. Key concepts: regression coverage, interface stability, and output integrity.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from lunar_planner.contracts import (
    PlannerContractError,
    load_planner_yaml,
    load_profile,
    load_schema,
    validate_contract,
    validate_profile,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


PROFILE_ROOT = (
    REPO_ROOT / "app" / "backend" / "lunar_planner" / "resources" / "profiles"
)
PROFILE_PATHS = tuple(
    PROFILE_ROOT / filename
    for filename in (
        "direct-use.yaml",
        "new-workflow.yaml",
        "extend-workflow.yaml",
        "refine-workflow.yaml",
    )
)
SCHEMA_ROOT = REPO_ROOT / "app" / "backend" / "lunar_planner" / "resources" / "schemas"
PLANNER_SCHEMAS = tuple(sorted(SCHEMA_ROOT.glob("planner-*.schema.json")))


def _direct_profile() -> dict:
    """Direct profile."""
    return load_planner_yaml(PROFILE_ROOT / "direct-use.yaml")


def test_all_planner_schemas_are_namespaced_json_schema() -> None:
    """Verify all planner schemas are namespaced JSON schema."""
    assert {path.name for path in PLANNER_SCHEMAS} == {
        "planner-acceptance-v1.schema.json",
        "planner-dialogue-critic-v1.schema.json",
        "planner-dialogue-state-v1.schema.json",
        "planner-external-source-plan-v1.schema.json",
        "planner-plan-v1.schema.json",
        "planner-post-plan-evidence-verification-v1.schema.json",
        "planner-answer-control-readiness-v1.schema.json",
        "planner-answer-trust-assessment-v1.schema.json",
        "planner-claim-trust-assessment-v1.schema.json",
        "planner-generative-transformation-receipt-v1.schema.json",
        "planner-workflow-comparator-disposition-v1.schema.json",
        "planner-workflow-workload-inventory-v1.schema.json",
        "planner-workflow-effort-estimate-v1.schema.json",
        "planner-workflow-effort-assessment-v1.schema.json",
        "planner-workflow-effort-card-v1.schema.json",
        "planner-workflow-effort-invalidation-v1.schema.json",
        "planner-workflow-resource-estimate-v1.schema.json",
        "planner-workflow-resource-usage-v1.schema.json",
        "planner-workflow-cost-reconciliation-v1.schema.json",
        "planner-workflow-economics-report-v1.schema.json",
        "planner-workflow-effort-calibration-v1.schema.json",
        "planner-workflow-resource-profile-v1.schema.json",
        "planner-price-book-v1.schema.json",
        "planner-profile-v1.schema.json",
        "planner-proposed-skill-test-plan-v1.schema.json",
        "planner-provenance-reconciliation-v1.schema.json",
        "planner-next-step-guidance-v1.schema.json",
        "planner-delivery-package-v1.schema.json",
        "planner-w3c-provenance-export-v1.schema.json",
        "planner-request-v1.schema.json",
        "planner-requirement-ledger-v1.schema.json",
        "planner-report-workflow-inheritance-v1.schema.json",
        "planner-route-v1.schema.json",
        "planner-run-manifest-v1.schema.json",
        "planner-todo-event-v1.schema.json",
        "planner-workflow-draft-v1.schema.json",
        "planner-workflow-instantiation-v1.schema.json",
        "planner-workflow-refinement-cycle-v1.schema.json",
        "planner-contextual-outcome-quality-contract-v1.schema.json",
        "planner-route-delivery-quality-plan-v1.schema.json",
        "planner-quality-plan-review-v1.schema.json",
        "planner-contextual-quality-criterion-v1.schema.json",
        "planner-quality-assessment-v1.schema.json",
        "planner-final-delivery-decision-v1.schema.json",
    }
    for path in PLANNER_SCHEMAS:
        schema = json.loads(path.read_text(encoding="utf-8"))
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert schema["$id"].startswith("https://bioagents.local/schemas/planner-")


def test_plan_and_route_reference_reused_contracts() -> None:
    """Verify plan and route reference reused contracts."""
    plan = load_schema("lunar.planner.plan/v1")
    route = load_schema("lunar.planner.route/v1")
    serialized = json.dumps(plan)
    assert "skill-descriptor-v1.schema.json" in serialized
    assert "subworkflow-manifest-v1.json" in serialized
    assert "invocation-plan-v1.schema.json" in serialized
    assert route["properties"]["invocation_plan"]["$ref"].endswith(
        "invocation-plan-v1.schema.json"
    )
    # References prevent a copied, planner-owned description of these surfaces.
    assert "SkillDescriptor@1.0.0" not in serialized
    assert "bioagents.subworkflow/v1" not in serialized


@pytest.mark.parametrize("path", PROFILE_PATHS, ids=lambda path: path.stem)
def test_active_profiles_satisfy_semantic_contract(path: Path) -> None:
    """Verify active profiles satisfy semantic contract."""
    profile = load_profile(path, repo_root=REPO_ROOT)
    report = validate_profile(profile, repo_root=REPO_ROOT)
    assert report.valid, report.errors
    assert report.order[-1] == profile["release_stage_id"]
    assert len(report.producers) == sum(
        len(stage["outputs"]) for stage in profile["stages"]
    )


def test_strict_yaml_rejects_duplicate_and_merge_keys(tmp_path: Path) -> None:
    """Verify strict YAML rejects duplicate and merge keys."""
    duplicate = tmp_path / "duplicate.yaml"
    duplicate.write_text("schema_version: one\nschema_version: two\n", encoding="utf-8")
    with pytest.raises(PlannerContractError, match="duplicate YAML key"):
        load_planner_yaml(duplicate)

    merge = tmp_path / "merge.yaml"
    merge.write_text(
        "base: &base {status: planning}\ncopy: {<<: *base}\n", encoding="utf-8"
    )
    with pytest.raises(PlannerContractError, match="merge keys are forbidden"):
        load_planner_yaml(merge)


def test_profile_rejects_duplicates_forward_edges_and_cycles() -> None:
    """Verify profile rejects duplicates forward edges and cycles."""
    duplicate = _direct_profile()
    duplicate["stages"][1]["id"] = duplicate["stages"][0]["id"]
    assert any(
        "duplicate stage id" in error for error in validate_profile(duplicate).errors
    )

    forward = _direct_profile()
    forward["stages"][0]["dependencies"] = ["invocation_plan"]
    report = validate_profile(forward)
    assert any("not an earlier stage" in error for error in report.errors)
    assert any("acyclic" in error for error in report.errors)


def test_profile_rejects_multiple_producers_and_implicit_inputs() -> None:
    """Verify profile rejects multiple producers and implicit inputs."""
    profile = _direct_profile()
    profile["stages"][1]["outputs"] = ["skill_portfolio_packet"]
    report = validate_profile(profile)
    assert any("exactly one producer" in error for error in report.errors)

    profile = _direct_profile()
    profile["stages"][0]["inputs"].append("undeclared_context")
    report = validate_profile(profile)
    assert any("implicit input: undeclared_context" in error for error in report.errors)


def test_profile_requires_consumed_outputs_to_come_from_dependencies() -> None:
    """Verify profile requires consumed outputs to come from dependencies."""
    profile = _direct_profile()
    profile["stages"][2]["dependencies"] = ["candidate_gathering"]
    report = validate_profile(profile)
    assert any(
        "reuse_critical_packet is not produced by a dependency" in error
        for error in report.errors
    )


def test_profile_requires_admitted_owner_and_one_reachable_release() -> None:
    """Verify profile requires admitted owner and one reachable release."""
    profile = _direct_profile()
    profile["stages"][0]["owner_skill"] = "archive-only-placeholder"
    assert any(
        "owner does not resolve" in error for error in validate_profile(profile).errors
    )

    profile = _direct_profile()
    profile["stages"].append(
        {
            "id": "orphan",
            "owner_skill": "skill-portfolio-navigator",
            "inputs": ["verbatim_request"],
            "outputs": ["orphan_output"],
            "dependencies": [],
            "rule": "Planning only.",
        }
    )
    report = validate_profile(profile)
    assert any("do not reach release stage" in error for error in report.errors)
    assert any("only terminal" in error for error in report.errors)


def test_profile_fails_closed_on_execution_authority() -> None:
    """Verify profile fails closed on execution authority."""
    profile = _direct_profile()
    profile["status"] = "executable"
    profile["stages"][0]["runtime_owner"] = "catalog.workflows.some_runtime.run"
    report = validate_profile(profile)
    assert any("planning_only_non_executing" in error for error in report.errors)
    assert any("runtime_owner is not planning-only" in error for error in report.errors)


def test_minimum_request_and_digest_bound_acceptance_contracts() -> None:
    """Verify minimum request and digest bound acceptance contracts."""
    request = {
        "schema_version": "lunar.planner.request/v1",
        "request_id": "request-1",
        "objective": "Plan reuse without execution.",
        "inputs": {},
        "constraints": {},
        "authority": {
            "mode": "planning_only",
            "execution": "forbidden",
            "external_actions": "forbidden",
            "mutation": "forbidden",
        },
    }
    assert validate_contract(request).valid
    unsafe = copy.deepcopy(request)
    unsafe["authority"]["execution"] = "allowed"
    assert not validate_contract(unsafe).valid

    acceptance = {
        "schema_version": "lunar.planner.acceptance/v1",
        "acceptance_id": "acceptance-1",
        "run_id": "run-1",
        "plan_id": "plan-1",
        "plan_digest": f"sha256:{'a' * 64}",
        "decision": "accepted",
        "actor": "operator",
        "timestamp": "2026-08-27T12:00:00Z",
        "authority": "accept_plan_only",
    }
    assert validate_contract(acceptance).valid
    acceptance["plan_digest"] = "latest"
    assert not validate_contract(acceptance).valid


def test_reconciliation_requires_prospective_observed_separation() -> None:
    """Verify reconciliation requires prospective observed separation."""
    document = {
        "schema_version": "lunar.planner.provenance-reconciliation/v1",
        "components": [
            {
                "component_id": "stage-1",
                "prospective_status": "planned",
                "observed_status": "missing",
                "reconciliation_status": "missing_observation",
                "release_blocking": True,
                "prospective": {},
            }
        ],
        "summary": {
            "component_count": 1,
            "status_counts": {"missing_observation": 1},
            "release_blocking": True,
            "complete": False,
        },
        "boundary": {
            "prospective_is_observation": False,
            "allowed_privacy_classes": ["public"],
            "redactions_are_explicit_omissions": True,
        },
        "prospective_digest": f"sha256:{'b' * 64}",
        "observed_digest": f"sha256:{'c' * 64}",
        "reconciliation_digest": f"sha256:{'d' * 64}",
    }
    report = validate_contract(document)
    assert any(
        "distinguish prospective and observed" in error for error in report.errors
    )
