# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0

"""Confined, exact and auditable budget reservation accounting.

Purpose: provide the `budget accounting` implementation within `Lunar planner`. Key concepts: explicit responsibility, typed interfaces, and reproducible behavior. Principal I/O and failure semantics are defined by the public callables below.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from contextlib import ExitStack, contextmanager
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

from .portable import atomic_write_bytes, canonical_json, stable_hash


class BudgetAccountingError(RuntimeError):
    """Base class for budget-state failures."""


class BudgetExceeded(BudgetAccountingError):
    """An authorized reservation would exceed a configured scope."""


class BudgetIntegrityError(BudgetAccountingError):
    """Persisted state or ledger history failed verification."""


_SAFE = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.")
_HELD_GUARD = threading.Lock()
_HELD_LOCKDIRS: dict[str, tuple[int, str]] = {}


def _safe(value: object, label: str) -> str:
    """Safe."""
    text = str(value).strip()
    if not text or text in {".", ".."} or any(char not in _SAFE for char in text):
        raise BudgetAccountingError(f"unsafe {label}: {value!r}")
    return text


def _nano(value: object, label: str, *, positive: bool = False) -> int:
    """Nano."""
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < (1 if positive else 0)
    ):
        qualifier = "positive" if positive else "nonnegative"
        raise BudgetAccountingError(
            f"{label} must be a {qualifier} integer nano-currency amount"
        )
    return value


@contextmanager
def directory_lock(
    path: str | Path,
    *,
    timeout_seconds: float = 10.0,
    stale_after_seconds: float = 300.0,
) -> Iterator[None]:
    """Acquire a portable mkdir lock with bounded wait and stale cleanup.

    Atomic directory creation is the exclusion primitive. An ownership token
    prevents a former holder from removing a successor's lock, monotonic time
    bounds acquisition, and a same-thread second acquisition fails immediately.
    """

    lockdir = Path(path)
    if timeout_seconds < 0 or stale_after_seconds <= 0:
        raise BudgetAccountingError("lock timing values must be valid")
    lockdir.parent.mkdir(parents=True, exist_ok=True)
    if lockdir.parent.is_symlink() or lockdir.is_symlink():
        raise BudgetAccountingError("lock directory path is unsafe")
    identity = str(lockdir.resolve(strict=False))
    thread_id = threading.get_ident()
    token = uuid.uuid4().hex
    started = time.monotonic()
    while True:
        with _HELD_GUARD:
            held = _HELD_LOCKDIRS.get(identity)
            if held and held[0] == thread_id:
                raise BudgetAccountingError(
                    f"double acquisition of lock: {lockdir.name}"
                )
        try:
            lockdir.mkdir(mode=0o700)
            owner = {
                "pid": os.getpid(),
                "thread_id": thread_id,
                "token": token,
                "acquired_wall_time": time.time(),
            }
            (lockdir / "owner.json").write_text(
                canonical_json(owner) + "\n", encoding="utf-8"
            )
            with _HELD_GUARD:
                _HELD_LOCKDIRS[identity] = (thread_id, token)
            break
        except FileExistsError:
            with _HELD_GUARD:
                held_locally = identity in _HELD_LOCKDIRS
            try:
                stale = time.time() - lockdir.stat().st_mtime > stale_after_seconds
            except FileNotFoundError:
                continue
            if stale and not held_locally:
                owner_path = lockdir / "owner.json"
                try:
                    owner_path.unlink(missing_ok=True)
                    lockdir.rmdir()
                    continue
                except (FileNotFoundError, OSError):
                    pass
            if time.monotonic() - started >= timeout_seconds:
                raise BudgetAccountingError(f"timed out acquiring lock: {lockdir.name}")
            time.sleep(
                min(0.01, max(0.0, timeout_seconds - (time.monotonic() - started)))
            )
    try:
        yield
    finally:
        with _HELD_GUARD:
            held = _HELD_LOCKDIRS.get(identity)
            if held == (thread_id, token):
                del _HELD_LOCKDIRS[identity]
        owner_path = lockdir / "owner.json"
        try:
            persisted = json.loads(owner_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            persisted = {}
        if persisted.get("token") == token:
            owner_path.unlink(missing_ok=True)
            try:
                lockdir.rmdir()
            except FileNotFoundError:
                pass


class BudgetLedger:
    """Atomic multi-scope reservations with an append-only hash-chained ledger."""

    def __init__(self, root: str | Path, *, tenant_id: str, currency: str) -> None:
        """Initialize budget ledger."""
        requested = Path(root)
        if requested.exists() and requested.is_symlink():
            raise BudgetAccountingError("budget root cannot be a symlink")
        self.root = requested.resolve(strict=False)
        self.tenant_id = _safe(tenant_id, "tenant_id")
        self.currency = _safe(currency.upper(), "currency")
        self.tenant_root = self.root / self.tenant_id
        self.tenant_root.mkdir(parents=True, exist_ok=True)
        if (
            self.tenant_root.is_symlink()
            or not self.tenant_root.resolve().is_relative_to(self.root)
        ):
            raise BudgetAccountingError("tenant state escaped or traversed a symlink")
        (self.tenant_root / "locks").mkdir(exist_ok=True)
        self.state_path = self.tenant_root / "state.json"
        self.ledger_path = self.tenant_root / "events.jsonl"

    def _scope_lock(self, scope: str) -> Path:
        """Scope lock."""
        return self.tenant_root / "locks" / f"{_safe(scope, 'scope')}.lockdir"

    @contextmanager
    def _locked(self, scopes: Sequence[str]) -> Iterator[None]:
        """Locked."""
        names = sorted(set(_safe(scope, "scope") for scope in scopes))
        with ExitStack() as stack:
            # Global lock serializes the shared state file; sorted scope locks
            # preserve compatibility with sharded CostGuard implementations.
            stack.enter_context(directory_lock(self.tenant_root / ".state.lockdir"))
            for name in names:
                stack.enter_context(directory_lock(self._scope_lock(name)))
            yield

    def _empty(self) -> dict[str, Any]:
        """Empty."""
        return {
            "schema_version": "lunar.planner.budget-state/v1",
            "tenant_id": self.tenant_id,
            "currency": self.currency,
            "scopes": {},
            "reservations": {},
            "reconciliations": {},
            "invoices": {},
        }

    def _read(self) -> dict[str, Any]:
        """Read."""
        if not self.state_path.exists():
            return self._empty()
        if self.state_path.is_symlink():
            raise BudgetIntegrityError("state path is a symlink")
        try:
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise BudgetIntegrityError("invalid budget state") from exc
        if (
            state.get("tenant_id") != self.tenant_id
            or state.get("currency") != self.currency
        ):
            raise BudgetIntegrityError("budget state identity mismatch")
        return state

    def _write(self, state: Mapping[str, Any]) -> None:
        """Write."""
        atomic_write_bytes(
            self.state_path, (canonical_json(state) + "\n").encode(), mode=0o600
        )

    def _events(self) -> list[dict[str, Any]]:
        """Events."""
        if not self.ledger_path.exists():
            return []
        if self.ledger_path.is_symlink():
            raise BudgetIntegrityError("ledger path is a symlink")
        events = []
        previous = None
        for number, line in enumerate(
            self.ledger_path.read_text(encoding="utf-8").splitlines(), 1
        ):
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise BudgetIntegrityError(f"invalid ledger line {number}") from exc
            if (
                event.get("sequence") != number
                or event.get("previous_event_hash") != previous
            ):
                raise BudgetIntegrityError("ledger sequence or chain mismatch")
            digest = event.get("event_hash")
            if digest != stable_hash(
                {key: value for key, value in event.items() if key != "event_hash"}
            ):
                raise BudgetIntegrityError("ledger event digest mismatch")
            previous = digest
            events.append(event)
        return events

    def _append(
        self, kind: str, key: str, payload: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Append."""
        events = self._events()
        event = {
            "sequence": len(events) + 1,
            "event_kind": kind,
            "idempotency_key": key,
            "payload": deepcopy(dict(payload)),
            "payload_digest": stable_hash(payload),
            "previous_event_hash": events[-1]["event_hash"] if events else None,
        }
        event["event_hash"] = stable_hash(event)
        fd = os.open(self.ledger_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(fd, (canonical_json(event) + "\n").encode())
            os.fsync(fd)
        finally:
            os.close(fd)
        return event

    @staticmethod
    def _existing(
        collection: Mapping[str, Any], key: str, payload: Mapping[str, Any]
    ) -> dict[str, Any] | None:
        """Existing."""
        existing = collection.get(key)
        if existing is None:
            return None
        if existing.get("request_digest") != stable_hash(payload):
            raise BudgetAccountingError(f"idempotency collision for {key}")
        return deepcopy(existing)

    def configure_scope(self, scope: str, limit_nano: int) -> dict[str, Any]:
        """Configure scope."""
        scope = _safe(scope, "scope")
        limit = _nano(limit_nano, "limit_nano", positive=True)
        with self._locked([scope]):
            state = self._read()
            current = state["scopes"].get(scope)
            if current and current["limit_nano"] != limit:
                raise BudgetAccountingError("scope limits are immutable in a ledger")
            if not current:
                current = {
                    "limit_nano": limit,
                    "reserved_nano": 0,
                    "observed_not_invoiced_nano": 0,
                    "reconciled_nano": 0,
                }
                state["scopes"][scope] = current
                self._append(
                    "scope_configured",
                    f"scope:{scope}",
                    {"scope": scope, "limit_nano": limit},
                )
                self._write(state)
            return deepcopy(current)

    def reserve(
        self,
        reservation_id: str,
        amount_nano: int,
        scopes: Sequence[str],
        *,
        authorized: bool,
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Reserve."""
        reservation_id = _safe(reservation_id, "reservation_id")
        amount = _nano(amount_nano, "amount_nano", positive=True)
        scope_names = sorted(set(_safe(scope, "scope") for scope in scopes))
        if not authorized:
            raise BudgetAccountingError(
                "budget reservation requires explicit authority"
            )
        if not scope_names:
            raise BudgetAccountingError("reservation requires at least one scope")
        request = {
            "amount_nano": amount,
            "scopes": scope_names,
            "metadata": deepcopy(dict(metadata or {})),
        }
        with self._locked(scope_names):
            state = self._read()
            found = self._existing(state["reservations"], reservation_id, request)
            if found:
                return found
            for scope in scope_names:
                counter = state["scopes"].get(scope)
                if counter is None:
                    raise BudgetAccountingError(f"unconfigured budget scope: {scope}")
                committed = (
                    counter["reserved_nano"]
                    + counter["observed_not_invoiced_nano"]
                    + counter["reconciled_nano"]
                )
                if committed + amount > counter["limit_nano"]:
                    raise BudgetExceeded(f"reservation exceeds scope {scope}")
            record = {
                "reservation_id": reservation_id,
                "amount_nano": amount,
                "remaining_nano": amount,
                "scopes": scope_names,
                "status": "active",
                "request_digest": stable_hash(request),
                "metadata": request["metadata"],
            }
            for scope in scope_names:
                state["scopes"][scope]["reserved_nano"] += amount
            state["reservations"][reservation_id] = record
            self._append("reserved", reservation_id, request)
            self._write(state)
            return deepcopy(record)

    def release(
        self, reservation_id: str, release_id: str, amount_nano: int | None = None
    ) -> dict[str, Any]:
        """Release all or part of an unused reservation idempotently."""

        return self._release(
            reservation_id, release_id, amount_nano, event_kind="released"
        )

    def expire(self, reservation_id: str, expiry_id: str) -> dict[str, Any]:
        """Expire and release the complete unused portion of a reservation."""

        return self._release(reservation_id, expiry_id, None, event_kind="expired")

    def _release(
        self,
        reservation_id: str,
        release_id: str,
        amount_nano: int | None,
        *,
        event_kind: str,
    ) -> dict[str, Any]:
        """Release."""
        reservation_id, release_id = _safe(reservation_id, "reservation_id"), _safe(
            release_id, "release_id"
        )
        state_hint = self._read()
        reservation = state_hint["reservations"].get(reservation_id)
        if not reservation:
            raise BudgetAccountingError("unknown reservation")
        with self._locked(reservation["scopes"]):
            state = self._read()
            reservation = state["reservations"][reservation_id]
            amount = (
                reservation["remaining_nano"]
                if amount_nano is None
                else _nano(amount_nano, "amount_nano", positive=True)
            )
            request = {
                "reservation_id": reservation_id,
                "amount_nano": amount,
                "event_kind": event_kind,
            }
            found = self._existing(state["reconciliations"], release_id, request)
            if found:
                return found
            if amount > reservation["remaining_nano"]:
                raise BudgetAccountingError("release exceeds remaining reservation")
            for scope in reservation["scopes"]:
                state["scopes"][scope]["reserved_nano"] -= amount
            reservation["remaining_nano"] -= amount
            reservation["status"] = (
                ("expired" if event_kind == "expired" else "released")
                if reservation["remaining_nano"] == 0
                else "partially_released"
            )
            record = {
                "kind": event_kind,
                "amount_nano": amount,
                "request_digest": stable_hash(request),
            }
            state["reconciliations"][release_id] = record
            self._append(event_kind, release_id, request)
            self._write(state)
            return deepcopy(record)

    def reconcile_observation(
        self,
        reservation_id: str,
        observation_id: str,
        observed_nano: int,
        *,
        release_nano: int | None = None,
        final: bool = False,
    ) -> dict[str, Any]:
        """Reconcile observation."""
        reservation_id, observation_id = _safe(reservation_id, "reservation_id"), _safe(
            observation_id, "observation_id"
        )
        amount = _nano(observed_nano, "observed_nano")
        state_hint = self._read()
        reservation = state_hint["reservations"].get(reservation_id)
        if not reservation:
            raise BudgetAccountingError("unknown reservation")
        with self._locked(reservation["scopes"]):
            state = self._read()
            reservation = state["reservations"][reservation_id]
            release = (
                reservation["remaining_nano"]
                if final
                else (
                    min(amount, reservation["remaining_nano"])
                    if release_nano is None
                    else _nano(release_nano, "release_nano")
                )
            )
            request = {
                "reservation_id": reservation_id,
                "observed_nano": amount,
                "release_nano": release,
                "final": final,
            }
            found = self._existing(state["reconciliations"], observation_id, request)
            if found:
                return found
            if release > reservation["remaining_nano"]:
                raise BudgetAccountingError(
                    "reconciliation release exceeds reservation"
                )
            for scope in reservation["scopes"]:
                counter = state["scopes"][scope]
                counter["reserved_nano"] -= release
                counter["observed_not_invoiced_nano"] += amount
            reservation["remaining_nano"] -= release
            reservation["status"] = (
                "reconciled"
                if reservation["remaining_nano"] == 0
                else "partially_reconciled"
            )
            record = {
                "kind": "observation",
                "reservation_id": reservation_id,
                "observed_nano": amount,
                "released_nano": release,
                "scopes": reservation["scopes"],
                "invoice_status": "pending",
                "request_digest": stable_hash(request),
            }
            state["reconciliations"][observation_id] = record
            self._append("observed", observation_id, request)
            self._write(state)
            return deepcopy(record)

    def reconcile_invoice(
        self, observation_id: str, invoice_id: str, invoice_nano: int
    ) -> dict[str, Any]:
        """Reconcile invoice."""
        observation_id, invoice_id = _safe(observation_id, "observation_id"), _safe(
            invoice_id, "invoice_id"
        )
        invoice = _nano(invoice_nano, "invoice_nano")
        state_hint = self._read()
        observation = state_hint["reconciliations"].get(observation_id)
        if not observation or observation.get("kind") != "observation":
            raise BudgetAccountingError("unknown observation")
        request = {"observation_id": observation_id, "invoice_nano": invoice}
        with self._locked(observation["scopes"]):
            state = self._read()
            found = self._existing(state["invoices"], invoice_id, request)
            if found:
                return found
            observation = state["reconciliations"][observation_id]
            if observation["invoice_status"] != "pending":
                raise BudgetAccountingError(
                    "observation was already invoice-reconciled"
                )
            observed = observation["observed_nano"]
            for scope in observation["scopes"]:
                counter = state["scopes"][scope]
                counter["observed_not_invoiced_nano"] -= observed
                counter["reconciled_nano"] += invoice
            observation["invoice_status"] = "reconciled"
            record = {
                "observation_id": observation_id,
                "invoice_nano": invoice,
                "observed_nano": observed,
                "variance_nano": invoice - observed,
                "request_digest": stable_hash(request),
            }
            state["invoices"][invoice_id] = record
            self._append("invoice_reconciled", invoice_id, request)
            self._write(state)
            return deepcopy(record)

    def snapshot(self) -> dict[str, Any]:
        """Snapshot."""
        with self._locked([]):
            state = self._read()
            self._events()
            return deepcopy(state)
