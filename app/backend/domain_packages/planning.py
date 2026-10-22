# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Build planner ports exclusively from one authenticated ready package version."""

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any

from lunar_planner.config import PlannerConfig
from lunar_planner.ports import PlannerPorts

from .context import VersionNotFound, owned_context
from .repository import resources


class PlanningUnavailable(ValueError):
    """The selected package requires a policy worker that is not prepared."""


def decoded(value):
    return json.loads(value) if isinstance(value, str) else value


def digest(value):
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(
                value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            ).encode()
        ).hexdigest()
    )


@dataclass(frozen=True)
class SelectedCatalog:
    value: dict

    def snapshot(self):
        return deepcopy(self.value)

    def descriptors(self, scopes):
        return (
            deepcopy(self.value["skills"]) if set(scopes) & {"package", "all"} else []
        )

    def workflows(self):
        return deepcopy(self.value["workflow_packages"])

    def inspect(self, workflow_id):
        found = next(
            (
                row
                for row in self.value["workflow_packages"]
                if row["id"] == workflow_id or row["workflow_id"] == workflow_id
            ),
            None,
        )
        if found is None:
            raise LookupError("workflow not found in selected version")
        return deepcopy(found)

    def resolve(self, command_text, **kwargs):
        terms = set(re.findall(r"[a-z0-9]+", command_text.casefold()))
        candidates = []
        for row in self.value["skills"]:
            score = len(
                terms
                & set(
                    re.findall(
                        r"[a-z0-9]+",
                        row["name"].casefold() + " " + row["description"].casefold(),
                    )
                )
            )
            if score:
                candidates.append({**deepcopy(row), "score": score})
        candidates.sort(key=lambda row: (-row["score"], row["id"]))
        return {
            "status": "candidates" if candidates else "unavailable",
            "candidates": candidates[: kwargs.get("limit", 12)],
            "executed": False,
        }

    def plan(self, names, **kwargs):
        by_id = {row["id"]: row for row in self.value["skills"]}
        by_id.update({row["name"]: row for row in self.value["skills"]})
        selected = [by_id[name] for name in names if name in by_id]
        if len(selected) != len(names):
            return {
                "status": "blocked",
                "blockers": ["capability is absent from the selected version"],
                "executed": False,
            }
        permissions = sorted(
            {
                str(item)
                for row in selected
                for item in row.get("authority", {}).get("permissions", [])
            }
        )
        return {
            "status": "planned",
            "selected_skills": list(names),
            "aggregated_authority": {"permissions": permissions},
            "executed": False,
        }


@dataclass(frozen=True)
class SelectedArchetypes:
    policy: Any
    catalog: SelectedCatalog

    def archetypes(self):
        definitions = self.policy.evaluate("archetypes", {})
        if not isinstance(definitions, list) or any(
            not isinstance(row, dict) for row in definitions
        ):
            raise ValueError("invalid selected-package archetype policy")
        aliases = {}
        for workflow in self.catalog.workflows():
            for name in (
                workflow["id"],
                workflow["workflow_id"],
                *workflow.get("aliases", []),
            ):
                aliases[name.replace("_", "-")] = workflow["id"]
        return [
            {
                **deepcopy(row),
                "seed_surface_ids": [
                    aliases[seed.replace("_", "-")]
                    for seed in row.get("seed_surface_ids", [])
                    if seed.replace("_", "-") in aliases
                ],
            }
            for row in definitions
        ]


def _skill(document, path):
    descriptor = document["metadata"].get("descriptor", {})
    if not isinstance(descriptor, dict):
        descriptor = {}
    description = str(
        descriptor.get("description")
        or document["name"] + " " + document["instructions"]
    )
    row = {
        **deepcopy(descriptor),
        "id": "skill:" + document["id"],
        "name": document["id"],
        "display_name": document["name"],
        "scope": "package",
        "description": description,
        "purpose": str(descriptor.get("purpose", description)),
        "triggers": descriptor.get("triggers", description),
        "source_path": path,
        "content_digest": digest(document),
        "kind": "skill",
        "available": True,
        "invocation_posture": descriptor.get("invocation_posture", "instruction_only"),
        "interface": descriptor.get(
            "interface",
            {
                "inputs": {"status": "documented", "items": []},
                "outputs": {"status": "documented", "items": []},
            },
        ),
        "authority": descriptor.get("authority", {}),
        "package_document": deepcopy(document),
    }
    return row


async def planner_binding(connection, context, storage, *, policy_provider=None):
    """Resolve one immutable selection; imported Python is never loaded here."""
    if await owned_context(connection, context.user_id, context.version_id) != context:
        raise VersionNotFound("Package context does not match the owned version")
    version = await connection.fetchrow(
        "SELECT manifest,runtime_state FROM package_versions WHERE id=$1 AND user_id=$2",
        context.version_id,
        context.user_id,
    )
    manifest = decoded(version["manifest"])
    from .source_workflows import runtime_manifest

    manifest = runtime_manifest(manifest, storage.version_root(context))
    if (
        manifest["runtime"]["planning_hooks"]
        and policy_provider is None
        and version["runtime_state"] != "ready"
    ):
        raise PlanningUnavailable(
            "Prepare the selected package policy worker before planning"
        )
    skills = []
    for row in await resources(connection, context, "skills"):
        document = decoded(row["document"])
        path = next(
            item["document"]
            for item in manifest["collections"]["skills"]
            if item["id"] == document["id"]
        )
        skills.append(_skill(document, path))
    workflows = []
    for registration in manifest["runtime"]["workflows"]:
        inputs = [
            {
                "name": key,
                "type": value.get("type", "object"),
                "required": key in registration["input_schema"].get("required", []),
            }
            for key, value in registration["input_schema"].get("properties", {}).items()
        ]
        workflows.append(
            {
                "id": "workflow:" + registration["id"],
                "workflow_id": registration["id"],
                "canonical_id": registration["id"],
                "display_name": registration["name"],
                "name": registration["name"],
                "aliases": [registration["id"]],
                "kind": "workflow_package",
                "available": True,
                "source_path": registration["entry_file"],
                "content_digest": digest(registration),
                "description": registration["name"],
                "purpose": registration["name"],
                "invocation_posture": "declared_worker",
                "execution_posture": "worker_only",
                "interface": {
                    "inputs": {"status": "documented", "items": inputs},
                    "outputs": {
                        "status": "documented",
                        "items": [{"name": "result", "type": "object"}],
                    },
                },
                "registration": deepcopy(registration),
            }
        )
    reports = []
    for row in await connection.fetch(
        """SELECT r.id,r.logical_id,COALESCE(r.name,r.query) AS name,
            COALESCE(r.content,r.html) AS content,r.version,p.document FROM reports r
            LEFT JOIN package_resources p ON p.id=r.id AND p.user_id=r.user_id AND p.version_id=r.version_id
            WHERE r.user_id=$1 AND r.version_id=$2 ORDER BY r.id""",
        context.user_id,
        context.version_id,
    ):
        original = decoded(row["document"]) if row["document"] else {}
        reports.append(
            {
                **original,
                "id": row["logical_id"] or str(row["id"]),
                "name": row["name"],
                "content": row["content"],
                "version": row["version"],
            }
        )
    snapshot = {
        "schema_version": "lunar.planner.surface-index/v1",
        "authority": "derived_navigation_only",
        "context_identity": [
            str(context.user_id),
            str(context.package_id),
            str(context.version_id),
        ],
        "counts": {"skills": len(skills), "workflow_packages": len(workflows)},
        "skills": skills,
        "workflow_packages": workflows,
        "subworkflows": [],
        "data_sources": [
            decoded(row["document"])
            for row in await resources(connection, context, "data-sources")
        ],
        "reports": reports,
    }
    if manifest["runtime"]["planning_hooks"] and policy_provider is None:
        from .worker.runtime import load_runtime
        from .worker.policy import WorkerPolicy

        runtime = await load_runtime(
            connection, context.user_id, context.version_id, storage
        )
        policy_provider = WorkerPolicy(
            runtime, [row["id"] for row in skills + workflows]
        )
    catalog = SelectedCatalog(snapshot)
    config = PlannerConfig(
        state_root=storage.version_root(context) / "planner-state",
        context_identity=(
            str(context.user_id),
            str(context.package_id),
            str(context.version_id),
        ),
    )
    return config, PlannerPorts(
        surface=catalog,
        capability_catalog=catalog,
        invocation_router=catalog,
        workflows=catalog,
        domain_policy=policy_provider,
        archetypes=(
            SelectedArchetypes(policy_provider, catalog) if policy_provider else None
        ),
    )
