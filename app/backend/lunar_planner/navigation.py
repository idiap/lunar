# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Read-only nomination and review packets from the explicitly selected catalog."""

from copy import deepcopy
import json
import sys

from .archetypes import build_archetype_index, load_surface_index
from .config import PlannerConfig, bind_planner, current_config
from .contracts import canonical_digest
from .ports import PlannerPorts
from .staged_routing import gather_candidates, normalize_request


def _selected():
    identity = current_config().context_identity
    if (
        identity is None
        or len(identity) != 3
        or not all(isinstance(value, str) and value for value in identity)
    ):
        raise ValueError("Select an owned package version")
    surface = load_surface_index()
    if surface.get("context_identity", list(identity)) != list(identity):
        raise ValueError("Catalog snapshot belongs to another context")
    return identity, surface


def reference_scan(objective):
    """Nominate only selected-version components without deciding semantic reuse."""
    if not isinstance(objective, str) or not objective.strip():
        raise ValueError("objective must be nonempty text")
    identity, surface = _selected()
    retrieval = gather_candidates(normalize_request(objective), surface)
    candidates = retrieval["candidates"]
    return {
        "kind": "workflow_reference_scan",
        "objective": objective,
        "context_identity": list(identity),
        "snapshot_digest": canonical_digest(surface),
        "workflow_candidates": [row for row in candidates if row["kind"] != "skill"],
        "skill_candidates": [row for row in candidates if row["kind"] == "skill"],
        "archetypes": build_archetype_index(surface)["archetypes"],
        "sources": deepcopy(surface.get("data_sources", [])),
        "reports": deepcopy(surface.get("reports", [])),
        "status": "requires_semantic_review",
        "executed": False,
        "external_actions_performed": False,
        "dependencies_installed": False,
    }


def reuse_review_packet(objective, candidate_ids):
    """Gather complete imported contracts, leaving the review verdict to a reviewer."""
    packet = reference_scan(objective)
    _, surface = _selected()
    by_id = {
        str(row.get("id", row.get("name"))): row
        for row in [
            *surface.get("skills", []),
            *surface.get("workflow_packages", []),
            *surface.get("subworkflows", []),
        ]
    }
    if not isinstance(candidate_ids, list) or any(
        not isinstance(value, str) or value not in by_id for value in candidate_ids
    ):
        raise ValueError("review candidate is absent from the selected version")
    return {
        **packet,
        "kind": "reuse_critical_packet",
        "review_candidates": [
            deepcopy(by_id[value]) for value in dict.fromkeys(candidate_ids)
        ],
        "review_verdict": None,
        "implementation_authorized": False,
    }


def main(operation):
    """Project an explicit host-supplied JSON snapshot; never discover a filesystem."""
    value = json.load(sys.stdin)
    identity = tuple(value["context_identity"])

    class SuppliedSurface:
        def snapshot(self):
            return deepcopy(value["surface"])

    with bind_planner(
        PlannerConfig(context_identity=identity),
        PlannerPorts(surface=SuppliedSurface()),
    ):
        packet = (
            reference_scan(value["objective"])
            if operation == "scan"
            else reuse_review_packet(value["objective"], value["candidate_ids"])
        )
    print(json.dumps(packet, sort_keys=True))
    return 0
