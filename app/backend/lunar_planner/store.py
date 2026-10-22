# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0

"""Append-only planner event storage with confined, atomic filesystem writes.

Purpose: provide the `store` implementation within `Lunar planner`. Key concepts: explicit responsibility, typed interfaces, and reproducible behavior. Principal I/O and failure semantics are defined by the public callables below.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .config import current_config
from .ports import current_ports

from .portable import (
    PlatformSupportError,
    atomic_write_bytes,
    exclusive_file_lock,
)
from .portable import (
    canonical_json,
    stable_hash,
)

from .provenance import redact_private_values

_EVENT_KINDS = frozenset({"version", "todo", "acceptance"})
_SAFE_SEGMENT_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_."
)


class PlannerStoreError(RuntimeError):
    """Base error for planner persistence failures."""


class PathConfinementError(PlannerStoreError):
    """A requested path escaped the configured store or traversed a symlink."""


class IdempotencyCollisionError(PlannerStoreError):
    """An idempotency key was reused for a different canonical payload."""


class IntegrityError(PlannerStoreError):
    """Persisted append-only state failed its canonical integrity checks."""


def _utc_now() -> str:
    """Utc now."""
    return current_ports().clock.now().isoformat().replace("+00:00", "Z")


def _safe_segment(value: object, *, label: str) -> str:
    """Safe segment."""
    segment = str(value).strip()
    if (
        not segment
        or segment in {".", ".."}
        or any(character not in _SAFE_SEGMENT_CHARS for character in segment)
        or "/" in segment
        or "\\" in segment
    ):
        raise PathConfinementError(f"unsafe {label}: {value!r}")
    return segment


def _nonempty_text(value: object, *, label: str) -> str:
    """Nonempty text."""
    text = str(value).strip()
    if not text or any(ord(character) < 32 for character in text):
        raise ValueError(f"invalid {label}: {value!r}")
    return text


class PlannerStore:
    """Durable event service for one planner run.

    With no explicit ``root``, state is confined to the repository's
    ``artifacts/runs/planner`` tree.  Supplying ``root`` is the explicit
    temporary/test-root escape hatch; run paths remain confined beneath it.
    """

    def __init__(
        self,
        plan_id: str,
        *,
        root: str | Path | None = None,
        clock: Callable[[], str] | None = None,
    ) -> None:
        """Initialize planner store."""
        self.plan_id = _safe_segment(plan_id, label="plan_id")
        configured = current_config()
        repository_root = configured.repository_root
        default_root = configured.state_root
        if root is None and default_root is None:
            raise PathConfinementError(
                "planner state root must be passed or configured by the host"
            )
        if root is not None:
            requested_root = Path(root)
        else:
            assert default_root is not None
            requested_root = Path(default_root)
        if requested_root.is_symlink():
            raise PathConfinementError(
                f"planner root cannot be a symlink: {requested_root}"
            )
        self.root = requested_root.resolve(strict=False)
        if (
            root is None
            and repository_root is not None
            and not self.root.is_relative_to(repository_root.resolve())
        ):
            raise PathConfinementError("default planner root escaped the repository")
        self._clock = clock or _utc_now
        self._ensure_directory(self.root)
        self.run_root = self._path(self.plan_id)
        self._ensure_directory(self.run_root)
        self._ensure_directory(self._path(self.plan_id, "events"))

    def _path(self, *segments: str) -> Path:
        """Path."""
        safe = [_safe_segment(segment, label="path segment") for segment in segments]
        candidate = self.root.joinpath(*safe)
        resolved_parent = candidate.parent.resolve(strict=False)
        if not resolved_parent.is_relative_to(self.root):
            raise PathConfinementError(f"path escaped planner root: {candidate}")
        current = self.root
        for segment in safe:
            current = current / segment
            if current.exists() and current.is_symlink():
                raise PathConfinementError(f"symlink path rejected: {current}")
        return candidate

    def _ensure_directory(self, path: Path) -> None:
        """Ensure directory."""
        if path.exists() and (path.is_symlink() or not path.is_dir()):
            raise PathConfinementError(f"directory path is unsafe: {path}")
        path.mkdir(parents=True, exist_ok=True)
        if path.is_symlink():
            raise PathConfinementError(f"directory became a symlink: {path}")

    @contextmanager
    def _locked(self):
        """Locked."""
        lock_path = self._path(self.plan_id, ".store.lock")
        if lock_path.exists() and lock_path.is_symlink():
            raise PathConfinementError(f"lock path is a symlink: {lock_path}")
        try:
            with exclusive_file_lock(lock_path):
                yield
        except (OSError, PlatformSupportError) as exc:
            raise PathConfinementError(
                f"unsafe planner lock path: {lock_path}"
            ) from exc

    def _atomic_write(self, path: Path, content: bytes) -> None:
        """Atomic write."""
        if not path.parent.resolve(strict=False).is_relative_to(self.root):
            raise PathConfinementError(f"write escaped planner root: {path}")
        if path.exists() and path.is_symlink():
            raise PathConfinementError(f"write target is a symlink: {path}")
        self._ensure_directory(path.parent)
        if path.exists() and path.is_symlink():
            raise PathConfinementError(f"write target became a symlink: {path}")
        atomic_write_bytes(path, content, mode=0o600)

    def _ledger_path(self, event_kind: str) -> Path:
        """Ledger path."""
        kind = str(event_kind).strip().lower()
        if kind not in _EVENT_KINDS:
            raise ValueError(f"unsupported planner event kind: {event_kind!r}")
        return self._path(self.plan_id, "events", f"{kind}-events.jsonl")

    def _read_raw(self, kind: str) -> list[dict[str, Any]]:
        """Read raw."""
        path = self._ledger_path(kind)
        if not path.exists():
            return []
        if path.is_symlink():
            raise PathConfinementError(f"ledger is a symlink: {path}")
        rows: list[dict[str, Any]] = []
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), 1
        ):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise IntegrityError(
                    f"invalid {kind} ledger line {line_number}"
                ) from exc
            if not isinstance(row, dict):
                raise IntegrityError(f"non-object {kind} ledger line {line_number}")
            rows.append(row)
        return rows

    @staticmethod
    def _event_hash(row: Mapping[str, Any]) -> str:
        """Event hash."""
        return stable_hash(
            {key: value for key, value in row.items() if key != "event_hash"}
        )

    def read_events(
        self, event_kind: str | None = None, *, verify: bool = True
    ) -> list[dict[str, Any]]:
        """Read events in deterministic kind/sequence order and verify integrity."""

        kinds = [event_kind] if event_kind is not None else sorted(_EVENT_KINDS)
        rows: list[dict[str, Any]] = []
        for kind in kinds:
            previous_sequence = 0
            for row in self._read_raw(str(kind)):
                sequence = row.get("sequence")
                if verify and (
                    not isinstance(sequence, int) or sequence != previous_sequence + 1
                ):
                    raise IntegrityError(f"non-monotonic {kind} event sequence")
                if verify and row.get("event_hash") != self._event_hash(row):
                    raise IntegrityError(f"canonical hash mismatch for {kind} event")
                previous_sequence = sequence if isinstance(sequence, int) else 0
                rows.append(row)
        return sorted(
            rows, key=lambda row: (str(row["event_kind"]), int(row["sequence"]))
        )

    def _idempotency_match(
        self, key: str, payload_digest: str, kind: str
    ) -> dict[str, Any] | None:
        """Idempotency match."""
        for row in self.read_events():
            if row.get("idempotency_key") != key:
                continue
            if (
                row.get("payload_digest") == payload_digest
                and row.get("event_kind") == kind
            ):
                return row
            raise IdempotencyCollisionError(
                f"idempotency key {key!r} already identifies a different event"
            )
        return None

    def append_event(
        self,
        event_kind: str,
        payload: Mapping[str, Any],
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Atomically append a privacy-filtered event or return its exact replay."""

        kind = str(event_kind).strip().lower()
        self._ledger_path(kind)  # validation before locking
        key = _nonempty_text(idempotency_key, label="idempotency_key")
        safe_payload = redact_private_values(dict(payload))
        payload_digest = stable_hash(safe_payload)
        with self._locked():
            replay = self._idempotency_match(key, payload_digest, kind)
            if replay is not None:
                return replay
            existing = self._read_raw(kind)
            event: dict[str, Any] = {
                "schema_version": "lunar.planner.state-event/v1",
                "event_kind": kind,
                "event_id": stable_hash(
                    {
                        "plan_id": self.plan_id,
                        "event_kind": kind,
                        "idempotency_key": key,
                        "payload_digest": payload_digest,
                    }
                ),
                "plan_id": self.plan_id,
                "sequence": len(existing) + 1,
                "recorded_at": self._clock(),
                "idempotency_key": key,
                "payload_digest": payload_digest,
                "payload": safe_payload,
            }
            event["event_hash"] = self._event_hash(event)
            content = b"".join(
                (canonical_json(row) + "\n").encode("utf-8")
                for row in [*existing, event]
            )
            self._atomic_write(self._ledger_path(kind), content)
            return event

    def append_version(
        self,
        plan_version: str,
        payload: Mapping[str, Any],
        *,
        idempotency_key: str,
        predecessor_digest: str | None = None,
    ) -> dict[str, Any]:
        """Append a new immutable plan-version event and update its projection."""

        version = _safe_segment(plan_version, label="plan_version")
        packet = {
            "plan_version": version,
            "predecessor_digest": predecessor_digest,
            "version_payload": dict(payload),
        }
        event = self.append_event("version", packet, idempotency_key=idempotency_key)
        pointer = {
            "schema_version": "lunar.planner.current-version/v1",
            "plan_id": self.plan_id,
            "plan_version": version,
            "version_event_id": event["event_id"],
            "version_event_hash": event["event_hash"],
        }
        with self._locked():
            # Replaying an older version is a true no-op: it must never roll the
            # current pointer back from a later append.
            version_events = self._read_raw("version")
            if version_events and version_events[-1]["event_id"] == event["event_id"]:
                pointer_path = self._path(self.plan_id, "current-version.json")
                current_pointer = (
                    json.loads(pointer_path.read_text(encoding="utf-8"))
                    if pointer_path.exists()
                    else None
                )
                if current_pointer != pointer:
                    self._atomic_write(
                        pointer_path,
                        (json.dumps(pointer, indent=2, sort_keys=True) + "\n").encode(
                            "utf-8"
                        ),
                    )
        return event

    def append_todo(
        self,
        todo_id: str,
        previous_status: str | None,
        new_status: str,
        *,
        plan_version: str,
        idempotency_key: str,
        reason: str,
        evidence_digest: str | None = None,
        actor: str = "planner",
    ) -> dict[str, Any]:
        """Append one TODO transition; historical transitions are never edited."""

        payload = {
            "todo_id": _nonempty_text(todo_id, label="todo_id"),
            "plan_version": _safe_segment(plan_version, label="plan_version"),
            "previous_status": previous_status,
            "new_status": str(new_status),
            "reason": str(reason),
            "evidence_digest": evidence_digest,
            "actor": str(actor),
        }
        return self.append_event("todo", payload, idempotency_key=idempotency_key)

    def append_acceptance(
        self,
        plan_version: str,
        plan_digest: str,
        *,
        decision: str,
        operator: str,
        authority: str,
        idempotency_key: str,
        evidence: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Append acceptance evidence bound to one exact plan digest."""

        payload = {
            "plan_version": _safe_segment(plan_version, label="plan_version"),
            "plan_digest": str(plan_digest),
            "decision": str(decision),
            "operator": str(operator),
            "authority": str(authority),
            "evidence": dict(evidence or {}),
        }
        return self.append_event("acceptance", payload, idempotency_key=idempotency_key)

    def compact(self, *, retain_recent_versions: int = 2) -> dict[str, Any]:
        """Write a lossless-evidence compaction projection without pruning logs.

        Every acceptance event and all events for accepted, current, or recent
        versions are retained.  Primary JSONL ledgers remain untouched.
        """

        if retain_recent_versions < 0:
            raise ValueError("retain_recent_versions must be non-negative")
        with self._locked():
            all_events = self.read_events()
            version_events = [
                row for row in all_events if row["event_kind"] == "version"
            ]
            recent = (
                {
                    str(row["payload"]["plan_version"])
                    for row in version_events[-retain_recent_versions:]
                }
                if retain_recent_versions
                else set()
            )
            pointer_path = self._path(self.plan_id, "current-version.json")
            current = None
            if pointer_path.exists():
                current = json.loads(pointer_path.read_text(encoding="utf-8")).get(
                    "plan_version"
                )
            if current:
                recent.add(str(current))
            acceptance = [
                row for row in all_events if row["event_kind"] == "acceptance"
            ]
            accepted_versions = {
                str(row["payload"].get("plan_version"))
                for row in acceptance
                if str(row["payload"].get("decision", "")).lower()
                in {"accepted", "accept"}
            }
            retained_versions = recent | accepted_versions
            retained = []
            for row in all_events:
                version = row.get("payload", {}).get("plan_version")
                if row["event_kind"] == "acceptance" or version in retained_versions:
                    retained.append(row)
            projection: dict[str, Any] = {
                "schema_version": "lunar.planner.compaction/v1",
                "plan_id": self.plan_id,
                "source_event_count": len(all_events),
                "retained_event_count": len(retained),
                "retained_plan_versions": sorted(retained_versions),
                "policy": {
                    "retain_recent_versions": retain_recent_versions,
                    "acceptance_events": "always",
                    "accepted_and_current_evidence": "always",
                    "primary_ledgers_pruned": False,
                },
                "events": retained,
            }
            projection["compaction_digest"] = stable_hash(projection)
            path = self._path(self.plan_id, "compactions", "latest.json")
            self._atomic_write(
                path,
                (json.dumps(projection, indent=2, sort_keys=True) + "\n").encode(
                    "utf-8"
                ),
            )
            return projection
