# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0

"""Tests for pure, authority-preserving planner control projections.

This module protects expected behavior for the corresponding workflow, script, or repository surface. Key concepts: regression coverage, interface stability, and output integrity.
"""

from __future__ import annotations

import pytest

from lunar_planner.control import (
    ControlPlaneError,
    project_milestones,
    reconcile_control_plane,
)


def _snapshot(**updates: object) -> dict[str, object]:
    """Return a valid canonical planner snapshot for one test."""

    snapshot: dict[str, object] = {
        "plan_id": "plan-1",
        "plan_version": 2,
        "objective": "Plan a bounded Lunar workflow",
        "status": "active",
        "stages": [
            {"id": "reuse", "status": "completed"},
            {"id": "contracts", "status": "running"},
            {"id": "release", "status": "pending"},
        ],
    }
    snapshot.update(updates)
    return snapshot


def test_milestone_projection_has_at_most_one_in_progress() -> None:
    """Ensure multiple internal running stages cannot leak into a public plan."""

    projected = project_milestones(
        [{"id": "one", "status": "running"}, {"id": "two", "status": "running"}]
    )
    assert [row["status"] for row in projected] == ["in_progress", "pending"]


def test_missing_goal_authority_stays_local_only() -> None:
    """Ensure archive or planner state never implies goal-creation authority."""

    result = reconcile_control_plane(_snapshot())
    assert result["status"] == "local_only"
    assert result["operations"] == []
    assert result["reverse_mutation_allowed"] is False


def test_explicit_goal_authority_forwards_only_explicit_budget() -> None:
    """Ensure budgets are neither invented nor inherited implicitly."""

    without_budget = reconcile_control_plane(
        _snapshot(), authority={"create_goal": True}
    )
    payload = without_budget["operations"][0]["payload"]
    assert "token_budget" not in payload
    with_budget = reconcile_control_plane(
        _snapshot(), authority={"create_goal": True, "token_budget": 1200}
    )
    assert with_budget["operations"][0]["payload"]["token_budget"] == 1200
    with pytest.raises(ControlPlaneError, match="positive integer"):
        reconcile_control_plane(
            _snapshot(), authority={"create_goal": True, "token_budget": 0}
        )


def test_remote_drift_never_reverse_mutates_planner_state() -> None:
    """Ensure a mismatched remote binding yields evidence rather than mutation."""

    result = reconcile_control_plane(
        _snapshot(),
        remote_goal={"planner_binding": "other@1", "objective": "different"},
        authority={"sync_plan": True},
    )
    assert result["status"] == "drift"
    assert result["operations"] == []
    assert result["reverse_mutation_allowed"] is False


def test_goal_terminal_projection_requires_canonical_closure_rules() -> None:
    """Ensure complete and blocked operations follow distinct hard gates."""

    complete = reconcile_control_plane(
        _snapshot(status="complete"),
        remote_goal={
            "planner_binding": "plan-1@2",
            "objective": "Plan a bounded Lunar workflow",
        },
        authority={"complete_goal": True},
    )
    assert any(
        row["operation"] == "update_goal" and row["payload"]["status"] == "complete"
        for row in complete["operations"]
    )

    premature = reconcile_control_plane(
        _snapshot(status="blocked", consecutive_blocker_count=2, terminal_impasse=True),
        remote_goal={
            "planner_binding": "plan-1@2",
            "objective": "Plan a bounded Lunar workflow",
        },
        authority={"block_goal": True},
    )
    assert not any(row["operation"] == "update_goal" for row in premature["operations"])
    blocked = reconcile_control_plane(
        _snapshot(status="blocked", consecutive_blocker_count=3, terminal_impasse=True),
        remote_goal={
            "planner_binding": "plan-1@2",
            "objective": "Plan a bounded Lunar workflow",
        },
        authority={"block_goal": True},
    )
    assert blocked["operations"][-1]["payload"]["status"] == "blocked"
