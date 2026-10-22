# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0

"""Integration contracts for the post-plan evidence-verification overlay.

This module protects expected behavior for the corresponding workflow, script, or repository surface. Key concepts: regression coverage, interface stability, and output integrity.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from lunar_planner.contracts import (
    load_profile,
    validate_profile,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

RESOURCE_ROOT = REPO_ROOT / "app" / "backend" / "lunar_planner" / "resources"
PROFILE_ROOT = RESOURCE_ROOT / "profiles"
HOOK_PATH = RESOURCE_ROOT / "hooks" / "planner-hooks.yaml"
MANIFEST_PATH = RESOURCE_ROOT / "planner-manifest.json"
OVERLAY_PROFILE = PROFILE_ROOT / "post-plan-reasoning-verification.yaml"
STAGE_ID = "post_plan_reasoning_verification"
OUTPUT_ID = "post_plan_evidence_verification"
OWNER = "post-plan-evidence-grounding-verifier"
SCHEMA_VERSION = "lunar.planner.post-plan-evidence-verification/v1"

PERSISTENT_PROFILES = {
    "new_workflow": PROFILE_ROOT / "new-workflow.yaml",
    "extend_existing_workflow": PROFILE_ROOT / "extend-workflow.yaml",
    "refine_output_problem": PROFILE_ROOT / "refine-workflow.yaml",
}


def _load_yaml(path: Path) -> dict:
    """Load YAML."""
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_persistent_profiles_add_verification_after_initial_plan() -> None:
    """Verify persistent profiles add verification after initial plan."""
    for mode, path in PERSISTENT_PROFILES.items():
        profile = load_profile(path, repo_root=REPO_ROOT)
        report = validate_profile(profile, repo_root=REPO_ROOT)
        assert report.valid, (mode, report.errors)

        stages = profile["stages"]
        positions = {stage["id"]: index for index, stage in enumerate(stages)}
        stage = next(stage for stage in stages if stage["id"] == STAGE_ID)
        release = next(
            stage for stage in stages if stage["id"] == profile["release_stage_id"]
        )

        assert stage["owner_skill"] == OWNER
        assert stage["owner_scope"] == "planner"
        assert stage["outputs"] == [OUTPUT_ID]
        assert SCHEMA_VERSION in stage["rule"]
        assert positions[STAGE_ID] < positions[profile["release_stage_id"]]
        assert OUTPUT_ID in release["inputs"]
        assert STAGE_ID in release["dependencies"]


def test_direct_use_omits_post_plan_verification() -> None:
    """Verify direct use omits post plan verification."""
    direct = _load_yaml(PROFILE_ROOT / "direct-use.yaml")
    serialized = json.dumps(direct, sort_keys=True)
    assert STAGE_ID not in {stage["id"] for stage in direct["stages"]}
    assert OUTPUT_ID not in serialized
    assert OWNER not in serialized


def test_reusable_overlay_profile_is_planning_only_and_standalone() -> None:
    """Verify reusable overlay profile is planning only and standalone."""
    profile = load_profile(OVERLAY_PROFILE, repo_root=REPO_ROOT)
    report = validate_profile(profile, repo_root=REPO_ROOT)
    assert report.valid, report.errors
    assert profile["status"] == "planning_only_non_executing"
    assert profile["mode"] == STAGE_ID
    assert profile["release_stage_id"] == STAGE_ID
    assert profile["root_inputs"] == [
        "base_plan",
        "base_plan_digest",
        "authority_envelope",
    ]
    assert profile["stages"][0]["outputs"] == [OUTPUT_ID]
    rule = profile["stages"][0]["rule"]
    assert SCHEMA_VERSION in rule
    assert "without executing, mutating, or rerouting" in rule


def test_hook_and_manifest_register_one_additive_overlay() -> None:
    """Verify hook and manifest register one additive overlay."""
    hooks = _load_yaml(HOOK_PATH)
    overlay = hooks["verification_overlays"][STAGE_ID]
    assert overlay == {
        "source": "../profiles/post-plan-reasoning-verification.yaml",
        "stage_id": STAGE_ID,
        "owner_skill": OWNER,
        "output": OUTPUT_ID,
        "schema_version": SCHEMA_VERSION,
        "applies_to": list(PERSISTENT_PROFILES),
        "excluded_modes": ["direct_use"],
        "placement": "after_initial_plan_before_release_or_refinement_review",
        "mutation": "forbidden",
        "execution": "forbidden",
    }
    assert (HOOK_PATH.parent / overlay["source"]).resolve() == OVERLAY_PROFILE.resolve()

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    registration = manifest["post_plan_verification"]
    packaged_skills = list(RESOURCE_ROOT.parent.glob("skills/*/SKILL.md"))
    assert manifest["planner_skill_count"] == len(packaged_skills)
    assert registration["schema_version"] == SCHEMA_VERSION
    assert registration["applies_to"] == list(PERSISTENT_PROFILES)
    assert registration["excluded_modes"] == ["direct_use"]
    assert registration["authority"] == "planning_only_non_executing"
    assert (
        RESOURCE_ROOT.parent / registration["profile"]
    ).resolve() == OVERLAY_PROFILE.resolve()
    assert (RESOURCE_ROOT.parent / registration["schema"]).is_file()


def test_module_resources_and_docs_preserve_planning_boundary() -> None:
    """Verify module resources and docs preserve the planning boundary."""
    assert (RESOURCE_ROOT / "schemas" / "planner-request-v1.schema.json").is_file()
    assert OVERLAY_PROFILE.is_file()

    readme = (REPO_ROOT / "planner" / "README.md").read_text(encoding="utf-8")
    lifecycle = (
        REPO_ROOT / "planner" / "lifecycle" / "post-plan-reasoning-verification.md"
    ).read_text(encoding="utf-8")
    assert "Reusable post-plan reasoning verification overlay" in readme
    assert "Direct-use planning omits the stage" in lifecycle
    assert "verification_ready" in lifecycle
    assert "evidence_validated" in lifecycle
