# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Process-local opaque state for chaining canonical MCP tool calls safely."""

from __future__ import annotations

import copy
import secrets
from threading import RLock
from dataclasses import dataclass
from typing import Any

from domain_packages.context import CURRENT_VERSION, PackageContext, SelectionRequired


@dataclass(frozen=True)
class _StoredValue:
    kind: str
    value: Any
    context: PackageContext


class OpaqueStateStore:
    """Keep signed payloads server-side instead of round-tripping them through a model."""

    def __init__(self) -> None:
        self._values: dict[str, _StoredValue] = {}
        self._lock = RLock()

    def put(self, kind: str, value: Any) -> str:
        context = CURRENT_VERSION.get()
        if context is None:
            raise SelectionRequired(
                "Select a package version before storing planner state"
            )
        reference = f"{kind}-{secrets.token_urlsafe(18)}"
        with self._lock:
            self._values[reference] = _StoredValue(
                kind=kind, value=copy.deepcopy(value), context=context
            )
        return reference

    def get(self, reference: str, kind: str) -> Any:
        with self._lock:
            stored = self._values.get(reference)
            if (
                stored is None
                or stored.kind != kind
                or stored.context != CURRENT_VERSION.get()
            ):
                raise ValueError(f"unknown or expired {kind} reference")
            return copy.deepcopy(stored.value)

    def take(self, reference: str, kind: str) -> Any:
        with self._lock:
            stored = self._values.get(reference)
            if (
                stored is None
                or stored.kind != kind
                or stored.context != CURRENT_VERSION.get()
            ):
                raise ValueError(f"unknown or expired {kind} reference")
            del self._values[reference]
            return copy.deepcopy(stored.value)

    def clear(self) -> None:
        context = CURRENT_VERSION.get()
        if context is None:
            raise SelectionRequired(
                "Select a package version before clearing planner state"
            )
        with self._lock:
            self._values = {
                key: value
                for key, value in self._values.items()
                if value.context != context
            }


STATE = OpaqueStateStore()
