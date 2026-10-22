# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0

"""Tests for explicit no-op and bounded skill benchmark planning.

This module protects expected behavior for the corresponding workflow, script, or repository surface. Key concepts: regression coverage, interface stability, and output integrity.
"""

from __future__ import annotations

import pytest

from lunar_planner.benchmark import (
    BenchmarkPlanError,
    plan_paired_skill_benchmark,
)


def _change() -> dict[str, str]:
    """Return one bounded skill-change record."""

    return {
        "skill": "example-skill",
        "baseline_digest": "a" * 64,
        "candidate_digest": "b" * 64,
        "reuse_review_digest": "c" * 64,
    }


def test_no_skill_change_is_explicit_noop() -> None:
    """Ensure this planner implementation does not invent a benchmark need."""

    result = plan_paired_skill_benchmark([])
    assert result == {
        "schema_version": "lunar.planner.skill-benchmark/v1",
        "status": "noop",
        "reason": "no_skill_change",
        "subprocess_started": False,
    }


def test_candidate_benchmark_requires_explicit_authority_and_pins() -> None:
    """Ensure a later real skill change cannot silently start Codex."""

    with pytest.raises(BenchmarkPlanError, match="authority"):
        plan_paired_skill_benchmark([_change()])
    with pytest.raises(BenchmarkPlanError, match="pinned fixtures"):
        plan_paired_skill_benchmark(
            [_change()], authority={"allow_codex_exec": True, "sandbox": "read_only"}
        )
    result = plan_paired_skill_benchmark(
        [_change()],
        fixtures=[{"id": "direct", "input_digest": "d" * 64}],
        evaluator={"model": "pinned", "rubric_digest": "e" * 64, "budget": 1000},
        authority={"allow_codex_exec": True, "sandbox": "read_only"},
    )
    assert result["status"] == "ready_for_external_execution"
    assert result["subprocess_started"] is False
    assert len(result["manifest_digest"]) == 64


def test_same_baseline_and_candidate_is_rejected() -> None:
    """Ensure a cosmetic comparison cannot satisfy the paired gate."""

    change = _change()
    change["candidate_digest"] = change["baseline_digest"]
    with pytest.raises(BenchmarkPlanError, match="must differ"):
        plan_paired_skill_benchmark(
            [change],
            fixtures=[{"id": "direct"}],
            evaluator={"model": "pinned", "rubric_digest": "e" * 64, "budget": 1},
            authority={"allow_codex_exec": True, "sandbox": "read_only"},
        )
