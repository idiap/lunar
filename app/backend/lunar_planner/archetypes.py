# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0

"""Derived, non-executable navigation index for reusable workflow archetypes.

Archetypes in this module are deliberately not another workflow registry.  They
identify reusable structure shared by two or more admitted surfaces and are
omitted whenever a named workflow or promoted subworkflow already provides the
same exact surface.  The resulting rows can nominate planning bases only.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .ports import current_ports

SCHEMA_VERSION = "lunar.planner.archetype-index/v1"
SUPPORTED_SURFACE_SCHEMAS = {
    "lunar.planner.surface-index/v1",
    "lunar.planner.surface-index/v2",
}


# These definitions describe structures demonstrated by multiple current
# workflows.  Seed IDs are resolved through the generated all-surface index;
# missing/retired seeds are ignored instead of being recreated as placeholders.


def load_surface_index(*, repo_root=None, index_path=None) -> dict[str, Any]:
    """Read the selected host snapshot; no checkout or filesystem fallback exists."""
    if repo_root is not None or index_path is not None:
        raise ValueError(
            "planner navigation must come from the selected surface provider"
        )
    provider = current_ports().surface
    if provider is None:
        raise ValueError("Select a package version before planning")
    payload = json.loads(json.dumps(provider.snapshot()))
    if (
        payload.get("authority") != "derived_navigation_only"
        or payload.get("schema_version") not in SUPPORTED_SURFACE_SCHEMAS
    ):
        raise ValueError("invalid selected planner surface")
    return payload


def build_archetype_index(
    surface_index: Mapping[str, Any] | None = None,
    *,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    """Return only reusable structures not covered by an exact current surface."""

    source = dict(surface_index or load_surface_index(repo_root=repo_root))
    workflows = list(source.get("workflow_packages", ()))
    subworkflows = list(source.get("subworkflows", ()))
    admitted = {
        str(row["id"]): row
        for row in (*workflows, *subworkflows)
        if row.get("available", False)
    }
    rows: list[dict[str, Any]] = []
    provider = current_ports().archetypes
    for definition in (provider.archetypes() if provider is not None else ()):
        # Exact admitted surfaces remain the canonical reuse route, so a same-ID
        # archetype would be redundant and is intentionally excluded.
        if definition["id"] in admitted:
            continue
        seeds = [
            surface_id
            for surface_id in definition["seed_surface_ids"]
            if surface_id in admitted
        ]
        if len(seeds) < 2:
            continue
        rows.append(
            {
                "id": definition["id"],
                "kind": "derived_uncovered_archetype",
                "status": "navigation_candidate",
                "title": definition["title"],
                "family": definition["family"],
                "facets": list(definition["facets"]),
                "structure": definition["structure"],
                **(
                    {"control_blueprint": definition["control_blueprint"]}
                    if definition.get("control_blueprint")
                    else {}
                ),
                "seed_surface_ids": seeds,
                "coverage": "uncovered_by_exact_surface",
                "executable": False,
                "semantic_review_required": True,
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "authority": "derived_navigation_only",
        "source_index_schema_version": source.get("schema_version"),
        "selection_boundary": (
            "Archetype rows nominate uncovered reusable structures only. They do not "
            "select, bind, create, or execute workflows or skills."
        ),
        "archetypes": rows,
        "count": len(rows),
    }


def match_archetypes(
    query: str,
    archetype_index: Mapping[str, Any],
    *,
    limit: int = 3,
) -> list[dict[str, Any]]:
    """Deterministically shortlist archetypes; semantic review owns selection."""

    if limit < 1:
        raise ValueError("limit must be positive")
    tokens = set(re.findall(r"[a-z0-9]+", query.casefold()))
    scored: list[tuple[int, str, Mapping[str, Any], list[str]]] = []
    for row in archetype_index.get("archetypes", ()):
        facet_hits = sorted(tokens.intersection(row.get("facets", ())))
        if not facet_hits:
            continue
        score = len(facet_hits)
        scored.append((score, str(row["id"]), row, facet_hits))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [
        {
            "id": row["id"],
            "kind": row["kind"],
            "score": score,
            "rationale": [f"problem facet: {facet}" for facet in hits],
            "semantic_review_required": True,
        }
        for score, _identifier, row, hits in scored[:limit]
    ]
