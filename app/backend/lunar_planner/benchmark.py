# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0

"""Plan, but never execute, paired generative skill benchmarks.

The planner emits an explicit no-op when no admitted skill changes.  A real
candidate produces an authority-bounded benchmark manifest that another
repository-maintenance process may execute; this module never starts Codex or
any other subprocess.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any


class BenchmarkPlanError(ValueError):
    """Raised when a requested generative comparison is under-specified."""


def _digest(payload: Mapping[str, Any]) -> str:
    """Return the stable manifest digest."""

    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def plan_paired_skill_benchmark(
    changed_skills: Sequence[Mapping[str, Any]],
    *,
    fixtures: Sequence[Mapping[str, Any]] = (),
    evaluator: Mapping[str, Any] | None = None,
    authority: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a no-op or a complete non-executing paired benchmark manifest."""

    if not changed_skills:
        return {
            "schema_version": "lunar.planner.skill-benchmark/v1",
            "status": "noop",
            "reason": "no_skill_change",
            "subprocess_started": False,
        }
    authority = dict(authority or {})
    if authority.get("allow_codex_exec") is not True:
        raise BenchmarkPlanError(
            "paired benchmark requires explicit allow_codex_exec authority"
        )
    if authority.get("sandbox") != "read_only":
        raise BenchmarkPlanError("paired benchmark requires a read_only sandbox")
    if not fixtures:
        raise BenchmarkPlanError("paired benchmark requires pinned fixtures")
    evaluator = dict(evaluator or {})
    for field in ("model", "rubric_digest", "budget"):
        if field not in evaluator:
            raise BenchmarkPlanError(f"paired benchmark evaluator requires {field}")
    if not isinstance(evaluator["budget"], int) or evaluator["budget"] <= 0:
        raise BenchmarkPlanError("paired benchmark budget must be a positive integer")
    normalized: list[dict[str, str]] = []
    for index, change in enumerate(changed_skills):
        required = (
            "skill",
            "baseline_digest",
            "candidate_digest",
            "reuse_review_digest",
        )
        missing = [field for field in required if not change.get(field)]
        if missing:
            raise BenchmarkPlanError(
                f"changed_skills[{index}] missing fields: {', '.join(missing)}"
            )
        if change["baseline_digest"] == change["candidate_digest"]:
            raise BenchmarkPlanError("baseline and candidate digests must differ")
        normalized.append({field: str(change[field]) for field in required})
    payload = {
        "schema_version": "lunar.planner.skill-benchmark/v1",
        "status": "ready_for_external_execution",
        "changes": normalized,
        "fixtures": list(fixtures),
        "evaluator": evaluator,
        "sandbox": "read_only",
        "paired_baseline_required": True,
        "subprocess_started": False,
        "selection_boundary": (
            "This manifest does not execute Codex or promote a skill. Infrastructure "
            "failure, inconclusive comparison, or missing baseline must fail closed."
        ),
    }
    payload["manifest_digest"] = _digest(payload)
    return payload
