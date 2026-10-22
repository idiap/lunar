# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0

"""Explicit portable planner configuration and packaged resource paths.

Purpose: provide the `config` implementation within `Lunar planner`. Key concepts: explicit responsibility, typed interfaces, and reproducible behavior. Principal I/O and failure semantics are defined by the public callables below.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path


@dataclass(frozen=True)
class PlannerPaths:
    """Optional host-owned filesystem locations used by planner adapters."""

    surface_index: Path | None = None
    state_root: Path | None = None
    artifact_root: Path | None = None
    cache_root: Path | None = None


@dataclass(frozen=True)
class PlannerConfig:
    """Explicit planner configuration with no implicit repository discovery."""

    repository_root: Path | None = None
    surface_index: Path | None = None
    state_root: Path | None = None
    namespace: str = "lunar.planner"
    policy_version: str = "v1"
    paths: PlannerPaths | None = None
    context_identity: tuple[str, str, str] | None = None


_CONFIG: ContextVar[PlannerConfig] = ContextVar(
    "lunar_planner_config", default=PlannerConfig()
)


def configure(config: PlannerConfig) -> None:
    """Install the request-local planner configuration."""
    _CONFIG.set(config)


def current_config() -> PlannerConfig:
    """Return the active request-local planner configuration."""
    return _CONFIG.get()


def require_repository_root() -> Path:
    """Return the configured host root or fail with an actionable error."""
    repository_root = current_config().repository_root
    if repository_root is None:
        raise RuntimeError("repository_root must be passed or configured by the host")
    return repository_root.resolve()


def resource_path(kind: str, name: str) -> Path:
    """Resolve one confined resource shipped inside the planner package."""
    if (
        kind not in {"schemas", "profiles", "hooks", "policies"}
        or not name
        or "/" in name
        or "\\" in name
    ):
        raise ValueError("unsafe planner resource request")
    return Path(str(files("lunar_planner").joinpath("resources", kind, name)))


@contextmanager
def bind_planner(config: PlannerConfig, ports):
    """Bind one immutable host selection and its ports, restoring the caller on exit."""
    from .ports import _PORTS

    config_token = _CONFIG.set(config)
    ports_token = _PORTS.set(ports)
    try:
        yield
    finally:
        _PORTS.reset(ports_token)
        _CONFIG.reset(config_token)
