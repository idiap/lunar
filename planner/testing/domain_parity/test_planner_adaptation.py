# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0

"""Contract tests for the imported-and-adapted BioAgents planner design.

This module protects expected behavior for the corresponding workflow, script, or repository surface. Key concepts: regression coverage, interface stability, and output integrity.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from catalog.registry.skill_descriptor import load_skill_descriptors
from scripts.repository.build_planner_surface_index import (
    build_surface_index,
    write_surface_index,
)
from scripts.repository.check_planner_contracts import (
    _contract_file_errors,
    check_planner,
)
from scripts.repository.repo_layout import REPO_ROOT

PLANNER_ROOT = REPO_ROOT / "catalog" / "planner"
PROFILE_ROOT = PLANNER_ROOT / "src" / "lunar_planner" / "resources" / "profiles"
PROFILE_PATHS = tuple(
    PROFILE_ROOT / name
    for name in (
        "direct-use.yaml",
        "new-workflow.yaml",
        "extend-workflow.yaml",
        "refine-workflow.yaml",
    )
)


def _skill_names() -> set[tuple[str, str]]:
    """Return all admitted skill identities across both BioAgents scopes."""

    return {
        (descriptor.scope, descriptor.name)
        for descriptor in load_skill_descriptors(
            REPO_ROOT, scopes=("scientific", "planner", "project_support")
        )
    }


def test_profiles_use_only_current_bioagents_skills() -> None:
    """Ensure archive-only proposed owners never enter active profiles."""

    admitted = _skill_names()
    migration = json.loads(
        (PLANNER_ROOT / "reference" / "bioagents-reuse-map.json").read_text(
            encoding="utf-8"
        )
    )
    ignored = {
        owner
        for group in migration["owner_resolution_groups"]
        for owner in group["imported_owners"]
    }
    seen: set[str] = set()
    for path in PROFILE_PATHS:
        profile = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert profile["schema_version"] == "lunar.planner.profile/v1"
        assert profile["status"] == "planning_only_non_executing"
        assert profile["catalog_scope"] == "all_bioagents_skills_and_workflows"
        stage_ids = [stage["id"] for stage in profile["stages"]]
        assert len(stage_ids) == len(set(stage_ids))
        assert profile["release_stage_id"] in stage_ids
        prior: set[str] = set()
        for stage in profile["stages"]:
            scope = stage.get("owner_scope", "scientific")
            assert (scope, stage["owner_skill"]) in admitted
            assert stage["owner_skill"] not in ignored
            assert set(stage["dependencies"]) <= prior
            prior.add(stage["id"])
            seen.add(stage["owner_skill"])
    assert "skill-reuse-critical-reasoner" in seen
    assert "workflow-skill-gap-planner" in seen


def test_planner_surface_index_covers_every_skill_and_workflow() -> None:
    """Cover catalog agents and internal planner routes, but not project support."""

    index = build_surface_index(REPO_ROOT)
    descriptor_ids = {
        descriptor.data["id"]
        for descriptor in load_skill_descriptors(
            REPO_ROOT, scopes=("scientific", "planner")
        )
    }
    assert {row["id"] for row in index["skills"]} == descriptor_ids
    assert {row["scope"] for row in index["skills"]} == {"scientific", "planner"}
    assert all(row["scope"] != "project_support" for row in index["skills"])

    executable_packages = {
        path.parent.name
        for path in (REPO_ROOT / "catalog" / "workflows").glob("*/*/cli.py")
    }
    indexed_executables = {
        row["id"]
        for row in index["workflow_packages"]
        if row["kind"] == "named_executable_workflow"
    }
    assert indexed_executables == executable_packages

    manifest_ids = {
        yaml.safe_load(path.read_text(encoding="utf-8"))["id"]
        for path in (
            REPO_ROOT
            / "catalog"
            / "workflows"
            / "public"
            / "subworkflows"
            / "manifests"
        ).glob("*.yaml")
    }
    assert {row["id"] for row in index["subworkflows"]} == manifest_ids
    assert index["authority"] == "derived_navigation_only"


def test_generated_surface_index_is_deterministic_and_current(tmp_path: Path) -> None:
    """Protect deterministic generation and the checked-in planner view."""

    output = tmp_path / "index.json"
    assert write_surface_index(output, repo_root=REPO_ROOT)
    first = output.read_bytes()
    assert write_surface_index(output, repo_root=REPO_ROOT)
    assert output.read_bytes() == first
    assert write_surface_index(output, repo_root=REPO_ROOT, check=True)
    assert write_surface_index(
        REPO_ROOT
        / "artifacts"
        / "workflows"
        / "planner"
        / "bioagents-surface-index.json",
        repo_root=REPO_ROOT,
        check=True,
    )


def test_archive_only_skill_contexts_are_omitted() -> None:
    """Ensure absent archive proposals cannot masquerade as BioAgents skills."""

    assert not list(PLANNER_ROOT.rglob("CREATOR_CONTEXT.md"))
    assert (
        len(
            list((PLANNER_ROOT / "src" / "lunar_planner" / "skills").glob("*/SKILL.md"))
        )
        == 14
    )


def test_planner_paths_follow_repository_conventions() -> None:
    """Reject source-repository runtime and artifact paths from active contracts."""

    active_paths = (
        *PROFILE_PATHS,
        PROFILE_ROOT / "shared-lifecycle.yaml",
        PLANNER_ROOT
        / "src"
        / "lunar_planner"
        / "resources"
        / "hooks"
        / "planner-hooks.yaml",
    )
    combined = "\n".join(path.read_text(encoding="utf-8") for path in active_paths)
    assert "src/oncology_research_agents" not in combined
    assert "artifacts/planner/runs" not in combined
    assert "framework/meta_stacks.py" not in combined
    assert "execution_provenance_events" not in combined
    assert "artifacts/workflows/planner/bioagents-surface-index.json" in combined
    hook_policy = yaml.safe_load(
        (
            PLANNER_ROOT
            / "src"
            / "lunar_planner"
            / "resources"
            / "hooks"
            / "planner-hooks.yaml"
        ).read_text()
    )
    assert hook_policy["kernel"] is None
    assert hook_policy["status"] == "planning_only_non_executing"
    assert {
        (
            PLANNER_ROOT
            / "src"
            / "lunar_planner"
            / "resources"
            / "hooks"
            / row["source"]
        ).resolve()
        for row in hook_policy["profiles"].values()
    } == {path.resolve() for path in PROFILE_PATHS}
    lifecycle = yaml.safe_load(
        (PROFILE_ROOT / "shared-lifecycle.yaml").read_text(encoding="utf-8")
    )
    assert lifecycle["schema_version"] == "lunar.planner.lifecycle/v1"
    assert lifecycle["boundaries"]["execution"] == "forbidden"


def test_planner_markdown_links_are_local_and_resolve() -> None:
    """Verify relative Markdown links without following external references."""

    import re

    missing: list[str] = []
    for path in PLANNER_ROOT.rglob("*.md"):
        for target in re.findall(
            r"\[[^]]+\]\(([^)]+)\)", path.read_text(encoding="utf-8")
        ):
            target = target.split("#", 1)[0]
            if not target or "://" in target:
                continue
            resolved = (path.parent / target).resolve()
            if REPO_ROOT not in resolved.parents and resolved != REPO_ROOT:
                missing.append(f"{path}: escaping link {target}")
            elif not resolved.exists():
                missing.append(f"{path}: missing link {target}")
    assert missing == []


def test_integrated_planner_release_check_passes() -> None:
    """Keep profiles, generated views, and the planner-local TODO in closure."""

    report = check_planner(REPO_ROOT)
    assert report["status"] == "pass", report["errors"]
    assert report["unfinished_todos"] == []


def test_release_check_detects_missing_registered_schema_and_skill_reference(
    tmp_path: Path,
) -> None:
    """Verify release check detects missing registered schema and skill reference."""
    schema_root = tmp_path / "app/backend/lunar_planner/resources/schemas"
    schema_root.mkdir(parents=True)
    skill_root = tmp_path / "catalog/agents/example"
    skill_root.mkdir(parents=True)
    (skill_root / "SKILL.md").write_text(
        "Read [required contract](references/missing.md).\n",
        encoding="utf-8",
    )

    errors = _contract_file_errors(tmp_path)

    assert any("missing registered schema" in error for error in errors)
    assert any("missing local skill reference" in error for error in errors)
