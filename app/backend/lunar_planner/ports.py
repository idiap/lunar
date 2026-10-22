# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0

"""Typed host ports for the standalone planner core.

Purpose: provide the `ports` implementation within `Lunar planner`. Key concepts: explicit responsibility, typed interfaces, and reproducible behavior. Principal I/O and failure semantics are defined by the public callables below.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.resources import files
from typing import Any, Protocol

import yaml


class SurfaceProvider(Protocol):
    """Supply the selected version's already-validated navigation snapshot."""

    def snapshot(self) -> Mapping[str, Any]: ...


class DomainPolicyProvider(Protocol):
    """Evaluate selected-package policies through a host-controlled worker boundary."""

    def evaluate(self, operation: str, inputs: Mapping[str, Any]) -> Any: ...


class CapabilityCatalog(Protocol):
    """List effective capability descriptors supplied by a host."""

    def descriptors(self, scopes: Sequence[str]) -> Sequence[Mapping[str, Any]]: ...


class InvocationRouter(Protocol):
    """Resolve intent and compile dry-run invocation plans."""

    def resolve(self, command_text: str, **kwargs: Any) -> Mapping[str, Any]: ...
    def plan(self, names: Sequence[str], **kwargs: Any) -> Mapping[str, Any]: ...


class ExternalSourceProvider(Protocol):
    """Plan access to external sources without performing acquisition."""

    def compile(self, request: str) -> Mapping[str, Any]: ...
    def plan(self, **kwargs: Any) -> Mapping[str, Any]: ...


class PackageCatalogProvider(Protocol):
    """Search one host-supplied, release-pinned package capability index."""

    def compile(
        self,
        text: str,
        *,
        release: str,
        current_ports: Sequence[Mapping[str, Any]],
    ) -> Mapping[str, Any]: ...

    def search(
        self,
        package_need: Mapping[str, Any],
        *,
        index_descriptor: Mapping[str, Any],
        top_k: int,
    ) -> Mapping[str, Any]: ...

    def adjudicate(self, search_result: Mapping[str, Any]) -> Mapping[str, Any]: ...


class DomainPlannerProvider(Protocol):
    """Provide optional domain-specific planning behavior."""

    def plan(self, request: str, **kwargs: Any) -> Mapping[str, Any] | None: ...


class WorkflowProvider(Protocol):
    """Enumerate and inspect host-owned executable workflows."""

    def workflows(self) -> Sequence[Mapping[str, Any]]: ...
    def inspect(self, workflow_id: str) -> Mapping[str, Any]: ...


class ArchetypeProvider(Protocol):
    """Supply reusable workflow-construction archetypes."""

    def archetypes(self) -> Sequence[Mapping[str, Any]]: ...


class ArtifactStore(Protocol):
    """Read and atomically persist planner artifacts by logical identity."""

    def read(self, logical_id: str) -> bytes: ...
    def write(self, logical_id: str, payload: bytes) -> Mapping[str, Any]: ...


class DigestProvider(Protocol):
    """Produce host-approved deterministic content digests."""

    def digest(self, value: Any) -> str: ...


class ReasoningLogRenderer(Protocol):
    """Render normalized, user-visible planner decision traces."""

    def render(self, log: Mapping[str, Any]) -> str: ...


class QualityEvaluator(Protocol):
    """Evaluate contextual quality packets through an injected mechanism."""

    def evaluate(self, packet: Mapping[str, Any]) -> Mapping[str, Any]: ...


class RuntimeBindingRegistry(Protocol):
    """Resolve logical component operations to host runtime bindings."""

    def resolve(self, logical_id: str, operation: str) -> Mapping[str, Any] | None: ...


class SchemaResolver(Protocol):
    """Load versioned schemas by portable logical identifier."""

    def load(self, logical_id: str) -> Mapping[str, Any]: ...


class NonceProvider(Protocol):
    """Provide nonces for replay-safe authorization records."""

    def nonce(self) -> str: ...


class SigningKeyProvider(Protocol):
    """Resolve signing keys through host-controlled secret management."""

    def key(self, key_id: str) -> bytes: ...


class TrustPolicy(Protocol):
    """Decide whether a requested operation is permitted in context."""

    def permits(self, operation: str, context: Mapping[str, Any]) -> bool: ...


class Clock(Protocol):
    """Provide injectable time for deterministic authorization tests."""

    def now(self) -> datetime: ...


@dataclass(frozen=True)
class SystemClock:
    """Use the host system's timezone-aware UTC clock."""

    def now(self) -> datetime:
        """Return the provider's current timezone-aware timestamp."""
        return datetime.now(UTC)


@dataclass
class PlannerPorts:
    """Collect every optional host integration accepted by planner core."""

    surface: SurfaceProvider | None = None
    domain_policy: DomainPolicyProvider | None = None
    capability_catalog: CapabilityCatalog | None = None
    invocation_router: InvocationRouter | None = None
    external_sources: ExternalSourceProvider | None = None
    package_catalog: PackageCatalogProvider | None = None
    domain_planners: Mapping[str, DomainPlannerProvider] | None = None
    workflows: WorkflowProvider | None = None
    archetypes: ArchetypeProvider | None = None
    artifacts: ArtifactStore | None = None
    digests: DigestProvider | None = None
    reasoning_logs: ReasoningLogRenderer | None = None
    quality_evaluator: QualityEvaluator | None = None
    runtime_bindings: RuntimeBindingRegistry | None = None
    schemas: SchemaResolver | None = None
    nonces: NonceProvider | None = None
    signing_keys: SigningKeyProvider | None = None
    trust_policy: TrustPolicy | None = None
    clock: Clock = SystemClock()


_PORTS: ContextVar[PlannerPorts | None] = ContextVar(
    "lunar_planner_ports", default=None
)


def configure_ports(ports: PlannerPorts) -> None:
    """Install a complete request-local host port collection."""
    _PORTS.set(ports)


def current_ports() -> PlannerPorts:
    """Return the active request-local host port collection."""
    return _PORTS.get() or PlannerPorts()


def resolve_intent(command_text: str, **kwargs: Any) -> dict[str, Any]:
    """Resolve intent through the host router or return typed unavailability."""
    router = current_ports().invocation_router
    if router is None:
        return {
            "status": "unavailable",
            "candidates": [],
            "blockers": ["no invocation router provider configured"],
        }
    return dict(router.resolve(command_text, **kwargs))


def build_invocation_plan(names: Sequence[str], **kwargs: Any) -> dict[str, Any]:
    """Compile a dry-run invocation through the configured host router."""
    router = current_ports().invocation_router
    if router is None:
        return {
            "status": "unavailable",
            "selected_skills": list(names),
            "blockers": ["no invocation router provider configured"],
        }
    return dict(router.plan(names, **kwargs))


def resolve_runtime_binding(
    logical_id: str, operation: str
) -> Mapping[str, Any] | None:
    """Inspect binding metadata through the sole runtime-binding registry port.

    Resolution is planning-only: the returned descriptor is not imported or
    invoked, and lack of a registry remains explicit rather than becoming a
    semantic-generation fallback.
    """

    registry = current_ports().runtime_bindings
    if registry is None:
        return None
    value = registry.resolve(logical_id, operation)
    return dict(value) if isinstance(value, Mapping) else None


def plan_skill_operations(
    skill_id: str, *, operation_ids: Sequence[str] | None = None
) -> dict[str, Any]:
    """Plan reviewed operations for a configured host capability.

    This is the production composition boundary for operation-level profiles.
    It remains read-only and delegates binding metadata to the configured
    ``RuntimeBindingRegistry``.
    """

    from .capability_profiles import plan_profile_operations

    descriptors = skill_descriptors(("package", "planner"))
    descriptor = next((row for row in descriptors if row.get("id") == skill_id), None)
    if descriptor is None:
        return {
            "status": "blocked",
            "skill_id": skill_id,
            "tasks": [
                {"kind": "not_implemented", "reason": "skill descriptor unavailable"}
            ],
            "executed": False,
        }
    profile = descriptor.get("capability_profile")
    if not isinstance(profile, Mapping):
        return {
            "status": "blocked",
            "skill_id": skill_id,
            "tasks": [
                {
                    "kind": "profile_unavailable",
                    "reason": str(
                        descriptor.get(
                            "capability_profile_status",
                            "capability profile unavailable",
                        )
                    ),
                }
            ],
            "executed": False,
        }
    return plan_profile_operations(
        skill_id,
        str(descriptor["content_digest"]),
        {skill_id: profile},
        current_ports().runtime_bindings,
        operation_ids=operation_ids,
    )


def skill_descriptors(scopes: Sequence[str]) -> list[Mapping[str, Any]]:
    """Merge packaged planner skills with host-provided capability descriptors."""
    rows: list[Mapping[str, Any]] = []
    if "planner" in scopes:
        skill_root = files("lunar_planner").joinpath("skills")
        for entry in sorted(skill_root.iterdir(), key=lambda item: item.name):
            skill_md = entry.joinpath("SKILL.md")
            if not skill_md.is_file():
                continue
            text = skill_md.read_text(encoding="utf-8")
            frontmatter = (
                yaml.safe_load(text.split("---", 2)[1])
                if text.startswith("---")
                else {}
            )
            name = str((frontmatter or {}).get("name") or entry.name)
            rows.append(
                {
                    "id": f"planner:{name}",
                    "logical_id": f"planner://skill/{name}",
                    "name": name,
                    "scope": "planner",
                    "description": str(
                        (frontmatter or {}).get("description")
                        or "Packaged planner skill"
                    ),
                    "source_path": f"planner-resource://skills/{name}/SKILL.md",
                }
            )
    provider = current_ports().capability_catalog
    if provider is None:
        return rows
    provided = list(provider.descriptors(scopes))
    by_identity = {
        (str(item["scope"]), str(item["name"])): item for item in (*rows, *provided)
    }
    return [by_identity[key] for key in sorted(by_identity)]
