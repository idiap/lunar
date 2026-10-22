# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Reference nomination preserves explicit planning and scientific report roles."""

from copy import deepcopy
from lunar_planner.config import PlannerConfig, bind_planner
from lunar_planner.ports import PlannerPorts
from lunar_planner.navigation import reference_scan
from tests.planner.neutral_fixture import surface


def _scan(rows, objective):
    """Use caller-supplied test metadata and no filesystem discovery."""
    snapshot = surface()
    prototype = snapshot["skills"][0]
    snapshot["skills"] = []
    for name, description in rows:
        row = deepcopy(prototype)
        row.update(
            id="package:" + name,
            name=name,
            description=description,
            purpose=description,
            triggers=description,
        )
        snapshot["skills"].append(row)
    snapshot["counts"]["skills"] = len(rows)

    class Selected:
        def snapshot(self):
            return deepcopy(snapshot)

    with bind_planner(
        PlannerConfig(context_identity=("owner", "explicit-domain", "v1")),
        PlannerPorts(surface=Selected()),
    ):
        return reference_scan(objective)


def test_reference_scan_preserves_planning_roles_without_inventing_external_tools():
    """The selected package alone supplies reusable candidates and authority."""
    rows = [
        (
            "skill-portfolio-navigator",
            "Navigate portfolio and reuse routes for a workflow.",
        ),
        (
            "agentic-workflow-designer",
            "Translate workflow objectives into workflow packages.",
        ),
        ("external-validity-auditor", "Assess external validity of evidence sources."),
        ("paper-architect", "Turn analysis into a paper manuscript package."),
    ]
    result = _scan(
        rows,
        "Biomarker response workflow needing a new proteomic design and review path",
    )
    ids = {row["id"] for row in result["skill_candidates"]}
    assert "package:skill-portfolio-navigator" in ids
    assert ids <= {"package:" + name for name, _ in rows}
    assert result["status"] == "requires_semantic_review"
    assert not result["executed"] and not result["external_actions_performed"]


def test_reference_scan_retains_report_writers_critics_and_release_gate():
    """Reporting responsibilities survive nomination without an implied release."""
    rows = [
        ("workflow-paper-writer", "Write a controlled scientific paper manuscript."),
        ("paper-argument-critic", "Critique scientific paper arguments and rivals."),
        ("paper-structure-tester", "Test manuscript section structure."),
        ("manuscript-quality-release-gate", "Gate scientific manuscript release."),
    ]
    result = _scan(rows, "write a controlled scientific paper with section critiques")
    assert {"package:" + name for name, _ in rows} <= {
        row["id"] for row in result["skill_candidates"]
    }
    assert result["status"] == "requires_semantic_review" and not result["executed"]
