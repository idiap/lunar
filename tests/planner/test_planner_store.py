# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0

"""Focused durability and confinement tests for planner state.

This module protects expected behavior for the corresponding workflow, script, or repository surface. Key concepts: regression coverage, interface stability, and output integrity.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lunar_planner.store import (
    IdempotencyCollisionError,
    IntegrityError,
    PathConfinementError,
    PlannerStore,
)


def _store(tmp_path: Path) -> PlannerStore:
    """Store."""
    return PlannerStore("plan-1", root=tmp_path, clock=lambda: "2026-01-01T00:00:00Z")


def test_append_only_events_are_hashed_and_idempotent(tmp_path: Path) -> None:
    """Verify append only events are hashed and idempotent."""
    store = _store(tmp_path)
    first = store.append_version(
        "v1", {"objective": "test"}, idempotency_key="version-v1"
    )
    replay = store.append_version(
        "v1", {"objective": "test"}, idempotency_key="version-v1"
    )
    assert first == replay
    assert len(store.read_events("version")) == 1
    assert first["payload_digest"].startswith("sha256:")
    assert first["event_hash"].startswith("sha256:")

    with pytest.raises(IdempotencyCollisionError):
        store.append_version(
            "v1", {"objective": "changed"}, idempotency_key="version-v1"
        )


def test_replaying_old_version_does_not_roll_current_pointer_back(
    tmp_path: Path,
) -> None:
    """Verify replaying old version does not roll current pointer back."""
    store = _store(tmp_path)
    store.append_version(
        "v1", {"objective": "first"}, idempotency_key="plan:v1/version"
    )
    store.append_version(
        "v2", {"objective": "second"}, idempotency_key="plan:v2/version"
    )
    store.append_version(
        "v1", {"objective": "first"}, idempotency_key="plan:v1/version"
    )
    pointer = json.loads(
        (store.run_root / "current-version.json").read_text(encoding="utf-8")
    )
    assert pointer["plan_version"] == "v2"


def test_todo_acceptance_and_compaction_preserve_current_and_accepted_evidence(
    tmp_path: Path,
) -> None:
    """Verify todo acceptance and compaction preserve current and accepted evidence."""
    store = _store(tmp_path)
    for number in range(1, 5):
        store.append_version(
            f"v{number}", {"n": number}, idempotency_key=f"version-{number}"
        )
    store.append_todo(
        "T1",
        "proposed",
        "closed",
        plan_version="v1",
        idempotency_key="todo-1",
        reason="verified",
        evidence_digest="sha256:evidence",
    )
    acceptance = store.append_acceptance(
        "v1",
        "sha256:plan",
        decision="accepted",
        operator="user",
        authority="explicit",
        idempotency_key="accept-v1",
        evidence={"test_digest": "sha256:test"},
    )
    projection = store.compact(retain_recent_versions=1)
    assert projection["retained_plan_versions"] == ["v1", "v4"]
    assert acceptance in projection["events"]
    assert any(row["event_kind"] == "todo" for row in projection["events"])
    assert len(store.read_events("version")) == 4
    assert projection["policy"]["primary_ledgers_pruned"] is False


def test_paths_reject_traversal_and_symlinks(tmp_path: Path) -> None:
    """Verify paths reject traversal and symlinks."""
    with pytest.raises(PathConfinementError):
        PlannerStore("../escape", root=tmp_path)
    store = _store(tmp_path)
    ledger = store.run_root / "events" / "todo-events.jsonl"
    target = tmp_path / "outside.jsonl"
    target.write_text("", encoding="utf-8")
    try:
        ledger.symlink_to(target)
    except OSError:
        pytest.skip("directory policy does not permit symlink creation on this host")
    with pytest.raises(PathConfinementError):
        store.append_todo(
            "T1",
            None,
            "proposed",
            plan_version="v1",
            idempotency_key="todo-1",
            reason="new",
        )


def test_private_fields_are_redacted_before_persistence(tmp_path: Path) -> None:
    """Verify private fields are redacted before persistence."""
    store = _store(tmp_path)
    store.append_version(
        "v1",
        {"objective": "safe", "api_key": "do-not-store", "raw_prompt": "private"},
        idempotency_key="version-v1",
    )
    raw = (store.run_root / "events" / "version-events.jsonl").read_text(
        encoding="utf-8"
    )
    assert "do-not-store" not in raw
    assert 'private"' not in raw
    payload = json.loads(raw)["payload"]["version_payload"]
    assert payload["api_key"] == {"reason": "privacy_boundary", "status": "redacted"}


def test_reader_detects_tampered_canonical_hash(tmp_path: Path) -> None:
    """Verify reader detects tampered canonical hash."""
    store = _store(tmp_path)
    store.append_version("v1", {"objective": "test"}, idempotency_key="version-v1")
    ledger = store.run_root / "events" / "version-events.jsonl"
    row = json.loads(ledger.read_text(encoding="utf-8"))
    row["payload"]["version_payload"]["objective"] = "tampered"
    ledger.write_text(json.dumps(row) + "\n", encoding="utf-8")
    with pytest.raises(IntegrityError):
        store.read_events("version")
