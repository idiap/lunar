# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
# ruff: noqa: E402
# Imports follow sys.path setup for standalone execution.

"""Test closure readiness module.

Purpose: Decide whether a live planner state warrants a user-facing next-step suggestion by locating a concrete unresolved input, review, acceptance, repair, or gap obligation. Use near the end of a planning turn; omit suggestions when the request is closed, denied, merely informational, or lacks an actionable closure target. This module's responsibility is to verify observable content, failure behavior, invariants, and interface stability. Key concepts: planner, declared authority, and deterministic execution. Boundary: inputs, outputs, evidence, and failures remain governed by the `closure-readiness-assessor` skill contract. Principal I/O: consumes contract-defined values and emits contract-defined values.
"""

from pathlib import Path
import sys
import pytest

SKILL = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(SKILL / "src"), str(SKILL.parents[2])]
from closure_readiness_assessor import (  # pyright: ignore[reportMissingImports]
    assess_closure_readiness,
)


def test_content_closed_and_actionable_states():
    """Verify content closed and actionable states."""
    closed = assess_closure_readiness({"status": "complete", "mode": "plan"})
    open_state = assess_closure_readiness(
        {"status": "needs_input", "mode": "resume_plan", "blockers": ["plan id"]}
    )
    assert (closed["disposition"], open_state["obligations"]) == (
        "omit",
        ["input:planner-blocker"],
    )


def test_invalid_shape_fails_closed():
    """Verify invalid shape fails closed."""
    with pytest.raises(AttributeError):
        assess_closure_readiness(None)
    assert True


@pytest.mark.parametrize(
    "status,expected",
    [
        ("complete", "closed"),
        ("denied", "blocked"),
        ("open", "open_without_actionable_target"),
    ],
)
def test_property_status_projection(status, expected):
    """Verify property status projection."""
    result = assess_closure_readiness({"status": status, "mode": "plan"})
    assert result["closure_state"] == expected
