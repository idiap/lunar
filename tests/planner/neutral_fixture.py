# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Explicit non-biomedical catalog used only by generic planner regression tests."""

from copy import deepcopy


def surface():
    description = (
        "Explain checked formal claims and warehouse stock-count results, preserve source record context, "
        "distinguish correlation from a demonstrated local inventory discrepancy, "
        "and avoid unsupported purchasing recommendations. Produce a bounded explanation for a reader."
    )
    row = {
        "id": "package:stock-result-explainer",
        "name": "stock-result-explainer",
        "scope": "package",
        "description": description,
        "purpose": description,
        "triggers": description,
        "non_triggers": "",
        "source_path": "skills/stock-result-explainer/SKILL.md",
        "available": True,
        "invocation_posture": "instruction_only",
        "content_digest": "sha256:" + "1" * 64,
        "aliases": [],
        "interface": {
            "inputs": {"status": "documented", "items": []},
            "outputs": {
                "status": "documented",
                "items": [{"name": "explanation", "type": "text"}],
            },
        },
        "authority": {},
    }
    return {
        "schema_version": "lunar.planner.surface-index/v1",
        "authority": "derived_navigation_only",
        "counts": {"skills": 1},
        "skills": [row],
        "workflow_packages": [],
        "subworkflows": [],
    }


class NeutralSurface:
    def snapshot(self):
        return deepcopy(surface())
