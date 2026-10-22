# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0

"""Pure authority-preserving projections for optional Codex goal/plan sync.

This module never calls platform tools.  It derives proposed operations from
canonical planner state so an authenticated caller can decide whether to apply
them.  Remote state is observational evidence only and can never mutate the
planner snapshot in reverse.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any


class ControlPlaneError(ValueError):
    """Raised when canonical planner state cannot be projected safely."""


def _digest(value: Mapping[str, Any]) -> str:
    """Return a deterministic digest for an operation payload."""

    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def project_milestones(stages: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
    """Project atomic planner stages into concise ordered milestone status.

    Completed stages remain completed, the first running or ready stage becomes
    in progress, and every later stage remains pending.  The projection never
    accepts more than one in-progress stage.
    """

    projected: list[dict[str, str]] = []
    in_progress_seen = False
    for index, stage in enumerate(stages):
        stage_id = stage.get("id")
        status = stage.get("status", "pending")
        if not isinstance(stage_id, str) or not stage_id:
            raise ControlPlaneError(f"stage {index} requires a non-empty id")
        if status not in {"pending", "ready", "running", "completed", "blocked"}:
            raise ControlPlaneError(
                f"stage {stage_id} has unsupported status {status!r}"
            )
        if status == "completed":
            public_status = "completed"
        elif not in_progress_seen and status in {"ready", "running"}:
            public_status = "in_progress"
            in_progress_seen = True
        else:
            public_status = "pending"
        projected.append({"step": stage_id, "status": public_status})
    return projected


def reconcile_control_plane(
    planner_snapshot: Mapping[str, Any],
    *,
    remote_goal: Mapping[str, Any] | None = None,
    remote_plan: Sequence[Mapping[str, Any]] | None = None,
    authority: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return proposed goal/plan operations without applying external effects."""

    authority = dict(authority or {})
    required = ("plan_id", "plan_version", "objective", "status", "stages")
    missing = [field for field in required if field not in planner_snapshot]
    if missing:
        raise ControlPlaneError(
            f"planner snapshot missing fields: {', '.join(missing)}"
        )
    binding = f"{planner_snapshot['plan_id']}@{planner_snapshot['plan_version']}"
    milestones = project_milestones(planner_snapshot["stages"])
    result: dict[str, Any] = {
        "schema_version": "lunar.planner.control-reconciliation/v1",
        "binding": binding,
        "status": "synchronized",
        "milestones": milestones,
        "operations": [],
        "drift": [],
        "reverse_mutation_allowed": False,
    }

    if remote_goal is None:
        if not authority.get("create_goal"):
            result["status"] = "local_only"
            result["limitations"] = ["goal creation was not authorized"]
            return result
        payload: dict[str, Any] = {
            "objective": planner_snapshot["objective"],
            "planner_binding": binding,
        }
        if "token_budget" in authority:
            budget = authority["token_budget"]
            if not isinstance(budget, int) or isinstance(budget, bool) or budget <= 0:
                raise ControlPlaneError(
                    "explicit token_budget must be a positive integer"
                )
            payload["token_budget"] = budget
        result["operations"].append(
            {
                "operation": "create_goal",
                "payload": payload,
                "idempotency_key": _digest(payload),
            }
        )
    else:
        remote_binding = remote_goal.get("planner_binding")
        if remote_binding != binding:
            result["status"] = "drift"
            result["drift"].append(
                {
                    "field": "planner_binding",
                    "expected": binding,
                    "observed": remote_binding,
                }
            )
            return result
        if remote_goal.get("objective") != planner_snapshot["objective"]:
            result["status"] = "drift"
            result["drift"].append(
                {
                    "field": "objective",
                    "expected": planner_snapshot["objective"],
                    "observed": remote_goal.get("objective"),
                }
            )
            return result

    if remote_plan is not None and list(remote_plan) != milestones:
        result["drift"].append(
            {
                "field": "milestones",
                "expected": milestones,
                "observed": list(remote_plan),
            }
        )
    if authority.get("sync_plan") and list(remote_plan or []) != milestones:
        payload = {"planner_binding": binding, "plan": milestones}
        result["operations"].append(
            {
                "operation": "update_plan",
                "payload": payload,
                "idempotency_key": _digest(payload),
            }
        )

    planner_status = planner_snapshot["status"]
    if planner_status == "complete" and authority.get("complete_goal"):
        payload = {"planner_binding": binding, "status": "complete"}
        result["operations"].append(
            {
                "operation": "update_goal",
                "payload": payload,
                "idempotency_key": _digest(payload),
            }
        )
    elif planner_status == "blocked" and authority.get("block_goal"):
        blocker_count = planner_snapshot.get("consecutive_blocker_count", 0)
        if blocker_count >= 3 and planner_snapshot.get("terminal_impasse") is True:
            payload = {"planner_binding": binding, "status": "blocked"}
            result["operations"].append(
                {
                    "operation": "update_goal",
                    "payload": payload,
                    "idempotency_key": _digest(payload),
                }
            )
        else:
            result["limitations"] = [
                "blocked goal projection requires three consecutive blockers and terminal impasse"
            ]
    return result
