# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0

"""Skill-owned operation profiles and planning-only runtime binding resolution.

Profiles classify operations; they do not grant approval authority and they do
not execute code. Runtime bindings are resolved exclusively through the host's
``RuntimeBindingRegistry`` port. Prism artifacts are deliberately not an input
to this module.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

import jsonschema
import yaml

from .config import resource_path
from .ports import RuntimeBindingRegistry

PROFILE_SCHEMA_VERSION = "bioagents.skill-capability-profile/v1"
BINDING_SCHEMA_VERSION = "bioagents.runtime-binding/v1"

_PROFILE_SCHEMA = "skill-capability-profile-v1.schema.json"
_BINDING_SCHEMA = "runtime-binding-v1.schema.json"
_GENERATIVE_REQUIREMENTS = {"required", "conditional", "optional_presentation"}
_COMPUTATIONAL_ROLES = {
    "exact_transform",
    "retrieval",
    "symbolic_solver",
    "statistical_inference",
    "numerical_simulation",
}


def _canonical_digest(value: Mapping[str, Any], digest_field: str) -> str:
    """Canonical digest."""
    payload = {key: item for key, item in value.items() if key != digest_field}
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _schema(filename: str) -> Mapping[str, Any]:
    """Schema."""
    return json.loads(resource_path("schemas", filename).read_text(encoding="utf-8"))


def _shape_errors(value: Mapping[str, Any], filename: str) -> list[str]:
    """Shape errors."""
    validator = jsonschema.Draft202012Validator(_schema(filename))
    return [
        f"{'.'.join(str(part) for part in error.absolute_path) or '$'}: {error.message}"
        for error in sorted(
            validator.iter_errors(value), key=lambda item: list(item.absolute_path)
        )
    ]


def derive_skill_posture(operations: Sequence[Mapping[str, Any]]) -> str:
    """Derive presentation posture without consulting decision authority."""

    if not operations:
        return "unresolved"
    requirements = {str(item.get("generation_requirement")) for item in operations}
    if "unknown" in requirements:
        return "unresolved"
    essential_semantic = any(
        item.get("execution_character") == "semantic_generative"
        and item.get("generation_requirement") in {"required", "conditional"}
        for item in operations
    )
    nonsemantic_operations = [
        item
        for item in operations
        if item.get("reasoning_role") != "semantic_generation"
    ]
    if essential_semantic and nonsemantic_operations:
        return "hybrid"
    if essential_semantic:
        return "semantic_generative"
    if not nonsemantic_operations:
        return "instruction_only"
    characters = {
        str(item.get("execution_character")) for item in nonsemantic_operations
    }
    roles = {str(item.get("reasoning_role")) for item in nonsemantic_operations}
    if "" in characters:
        return "unresolved"
    if characters & {"seeded_stochastic", "stochastic_estimated", "provider_opaque"}:
        return "computational_stochastic"
    if roles == {"human_judgment"}:
        return "human_authority"
    if roles == {"orchestration"}:
        return "orchestration_only"
    if characters == {"non_executing"}:
        return "instruction_only"
    return "deterministic"


def validate_capability_profile(profile: Mapping[str, Any]) -> tuple[str, ...]:
    """Validate shape, profile identity, operation references, and boundaries."""

    errors = _shape_errors(profile, _PROFILE_SCHEMA)
    operations = [
        row for row in profile.get("operations", ()) if isinstance(row, Mapping)
    ]
    operation_ids = [str(row.get("operation_id")) for row in operations]
    if len(operation_ids) != len(set(operation_ids)):
        errors.append("operation_id values must be unique within a skill profile")
    known_operations = set(operation_ids)
    for operation in operations:
        operation_id = str(operation.get("operation_id", "<unknown>"))
        role = operation.get("reasoning_role")
        character = operation.get("execution_character")
        generation = operation.get("generation_requirement")
        controls = operation.get("generative_controls")
        binding_ids = tuple(operation.get("runtime_binding_ids", ()))
        binding_status = operation.get("binding_status")
        if role in _COMPUTATIONAL_ROLES and character == "semantic_generative":
            errors.append(
                f"{operation_id}: semantic generation cannot implement computational role {role}"
            )
        if generation == "prohibited" and character == "semantic_generative":
            errors.append(
                f"{operation_id}: prohibited generation conflicts with semantic_generative execution"
            )
        if generation in {"required", "conditional"} and not isinstance(
            controls, Mapping
        ):
            errors.append(
                f"{operation_id}: required or conditional generation needs generative_controls"
            )
        if generation not in _GENERATIVE_REQUIREMENTS and isinstance(controls, Mapping):
            errors.append(
                f"{operation_id}: generative_controls require a generative disposition"
            )
        if (
            role in _COMPUTATIONAL_ROLES
            and not binding_ids
            and binding_status not in {"unavailable", "instruction_only"}
        ):
            errors.append(
                f"{operation_id}: computational operation needs a binding or explicit unavailable/instruction_only status"
            )
        if binding_status == "bound" and not binding_ids:
            errors.append(f"{operation_id}: bound status requires runtime_binding_ids")
        if binding_status in {"unavailable", "instruction_only"} and binding_ids:
            errors.append(
                f"{operation_id}: {binding_status} status cannot declare runtime_binding_ids"
            )
        for handoff in operation.get("handoffs", ()):
            if handoff.get("target_operation_id") not in known_operations:
                errors.append(
                    f"{operation_id}: handoff target is not an operation in this profile"
                )
    derived = derive_skill_posture(operations)
    if profile.get("derived_posture") != derived:
        errors.append(
            f"derived_posture must be {derived}, not {profile.get('derived_posture')}"
        )
    expected_digest = _canonical_digest(profile, "capability_profile_digest")
    if profile.get("capability_profile_digest") != expected_digest:
        errors.append(
            "capability_profile_digest does not match canonical profile content"
        )
    if profile.get("review_status") == "reviewed" and not profile.get("reviewed_by"):
        errors.append("reviewed profiles require at least one reviewed_by identity")
    return tuple(dict.fromkeys(errors))


def validate_runtime_binding(binding: Mapping[str, Any]) -> tuple[str, ...]:
    """Validate a binding descriptor without importing or invoking its target."""

    errors = _shape_errors(binding, _BINDING_SCHEMA)
    kind = binding.get("binding_kind")
    availability = binding.get("availability", {})
    entrypoint = binding.get("entrypoint")
    if kind == "unavailable" and availability.get("status") != "unavailable":
        errors.append("unavailable binding kind requires unavailable status")
    if kind == "unavailable" and entrypoint not in (None, {"protocol": "none"}):
        errors.append("unavailable bindings cannot advertise an executable entrypoint")
    if kind not in {"unavailable", "instruction_only"} and not isinstance(
        entrypoint, Mapping
    ):
        errors.append("executable binding kinds require an entrypoint")
    if binding.get("fallback", {}).get(
        "mode"
    ) == "alternative_binding" and not binding.get("fallback", {}).get("binding_id"):
        errors.append("alternative_binding fallback requires binding_id")
    if binding.get("binding_digest") != _canonical_digest(binding, "binding_digest"):
        errors.append("binding_digest does not match canonical binding content")
    return tuple(dict.fromkeys(errors))


def _load_document(path: Path) -> Mapping[str, Any]:
    """Load document."""
    text = path.read_text(encoding="utf-8")
    value = json.loads(text) if path.suffix == ".json" else yaml.safe_load(text)
    if not isinstance(value, Mapping):
        raise ValueError(f"{path}: profile must be a mapping")
    return value


def load_capability_profiles(
    paths: Iterable[str | Path], *, skill_digests: Mapping[str, str] | None = None
) -> dict[str, dict[str, Any]]:
    """Load additive skill-owned sidecars and reject stale or Prism authority.

    Directories are searched recursively for JSON/YAML documents. Draft
    profiles remain loadable for inspection, but planner routing uses only
    profiles whose ``review_status`` is ``reviewed``.
    """

    documents: list[Path] = []
    for raw in paths:
        path = Path(raw)
        if any("prism" in part.casefold() for part in path.parts):
            raise ValueError(f"Prism is not an authoritative profile source: {path}")
        if path.is_dir():
            documents.extend(
                sorted(
                    item
                    for item in path.rglob("*")
                    if item.suffix in {".json", ".yaml", ".yml"}
                )
            )
        else:
            documents.append(path)
    profiles: dict[str, dict[str, Any]] = {}
    for path in documents:
        value = dict(_load_document(path))
        if value.get("schema_version") != PROFILE_SCHEMA_VERSION:
            continue
        errors = validate_capability_profile(value)
        if errors:
            raise ValueError(f"{path}: " + "; ".join(errors))
        skill_id = str(value["skill_id"])
        if skill_id in profiles:
            raise ValueError(f"duplicate capability profile for {skill_id}")
        expected = (skill_digests or {}).get(skill_id)
        if expected is not None and value["skill_digest"] != expected:
            raise ValueError(f"{path}: stale skill_digest for {skill_id}")
        profiles[skill_id] = value
    return profiles


def verification_method_for(operation: Mapping[str, Any]) -> tuple[str, ...]:
    """Return operation-declared verification, constrained by execution type."""

    declared = tuple(str(item) for item in operation.get("verification", ()))
    required = {
        "exact_deterministic": "exact_comparison",
        "numerically_deterministic": "tolerance_check",
        "seeded_stochastic": "statistical_diagnostics",
        "stochastic_estimated": "statistical_diagnostics",
        "provider_opaque": "evidence_fidelity",
        "semantic_generative": "evidence_fidelity",
        "human_variable": "human_review",
        "non_executing": "availability_only",
    }.get(str(operation.get("execution_character")))
    return tuple(dict.fromkeys((*declared, *((required,) if required else ()))))


def plan_profile_operations(
    skill_id: str,
    skill_digest: str,
    profiles: Mapping[str, Mapping[str, Any]],
    binding_registry: RuntimeBindingRegistry | None,
    *,
    operation_ids: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Compile non-executing invocations from one reviewed capability profile."""

    profile = profiles.get(skill_id)
    if profile is None:
        return {
            "status": "blocked",
            "skill_id": skill_id,
            "tasks": [
                {"kind": "not_implemented", "reason": "capability profile unavailable"}
            ],
            "executed": False,
        }
    profile_errors = validate_capability_profile(profile)
    if profile_errors:
        return {
            "status": "blocked",
            "skill_id": skill_id,
            "tasks": [
                {"kind": "invalid_profile", "reason": error} for error in profile_errors
            ],
            "executed": False,
        }
    if profile.get("skill_digest") != skill_digest:
        return {
            "status": "blocked",
            "skill_id": skill_id,
            "tasks": [{"kind": "stale_profile", "reason": "skill digest changed"}],
            "executed": False,
        }
    if profile.get("review_status") != "reviewed":
        return {
            "status": "advisory",
            "skill_id": skill_id,
            "profile_digest": profile.get("capability_profile_digest"),
            "tasks": [
                {
                    "kind": "profile_review_required",
                    "reason": "unreviewed metadata cannot control routing",
                }
            ],
            "executed": False,
        }
    requested = set(
        operation_ids or (str(row["operation_id"]) for row in profile["operations"])
    )
    known = {str(row["operation_id"]): row for row in profile["operations"]}
    unknown = sorted(requested - set(known))
    tasks: list[dict[str, Any]] = [
        {
            "kind": "not_implemented",
            "operation_id": operation_id,
            "reason": "operation is absent from reviewed profile",
        }
        for operation_id in unknown
    ]
    invocations: list[dict[str, Any]] = []
    for operation_id in sorted(requested & set(known)):
        operation = known[operation_id]
        registry_error: str | None = None
        try:
            binding_value = (
                binding_registry.resolve(skill_id, operation_id)
                if binding_registry
                else None
            )
        except (LookupError, ValueError) as exc:
            binding_value = None
            registry_error = str(exc)
        binding = dict(binding_value) if isinstance(binding_value, Mapping) else None
        binding_errors = (
            validate_runtime_binding(binding)
            if binding
            else (registry_error or "no runtime binding registry result",)
        )
        declared_ids = set(
            str(item) for item in operation.get("runtime_binding_ids", ())
        )
        if binding and binding.get("binding_id") not in declared_ids:
            binding_errors = (
                *binding_errors,
                "resolved binding_id is not declared by the operation",
            )
        if binding and binding.get("skill_id") != skill_id:
            binding_errors = (
                *binding_errors,
                "resolved binding skill_id does not match the profile",
            )
        if binding and binding.get("operation_id") != operation_id:
            binding_errors = (
                *binding_errors,
                "resolved binding operation_id does not match the requested operation",
            )
        if (
            binding is None
            or binding_errors
            or binding.get("availability", {}).get("status") != "available"
        ):
            unavailable_reason = (
                str(binding.get("availability", {}).get("reason", "unavailable"))
                if binding is not None
                else "no runtime binding registry result"
            )
            tasks.append(
                {
                    "kind": "binding_unavailable",
                    "operation_id": operation_id,
                    "binding_id": binding.get("binding_id") if binding else None,
                    "reason": (
                        "; ".join(binding_errors)
                        if binding_errors
                        else unavailable_reason
                    ),
                    "remediation": "install, authorize, repair, or explicitly retain the unavailable operation; semantic generation is not a substitute",
                }
            )
            continue
        invocations.append(
            {
                "polarity": "prospective",
                "skill_id": skill_id,
                "skill_digest": skill_digest,
                "operation_id": operation_id,
                "capability_profile_digest": profile["capability_profile_digest"],
                "binding_id": binding["binding_id"],
                "binding_digest": binding["binding_digest"],
                "execution_character": operation["execution_character"],
                "verification": list(verification_method_for(operation)),
                "authority": dict(profile.get("authority", {})),
                "executed": False,
                "observed_receipt": None,
            }
        )
    return {
        "status": (
            "ready"
            if invocations and not tasks
            else "degraded" if invocations else "blocked"
        ),
        "skill_id": skill_id,
        "profile_digest": profile["capability_profile_digest"],
        "invocations": invocations,
        "tasks": tasks,
        "executed": False,
    }


def record_observed_invocation(
    planned_invocation: Mapping[str, Any],
    *,
    input_digest: str,
    output_digest: str,
    environment_identity: str,
    observed_execution_character: str,
) -> dict[str, Any]:
    """Build an observed receipt bound to, but distinct from, a plan.

    The caller supplies observation data from an execution host. This helper
    neither runs the operation nor upgrades a mismatch into a successful run.
    """

    required = (
        "skill_id",
        "skill_digest",
        "operation_id",
        "capability_profile_digest",
        "binding_id",
        "binding_digest",
        "execution_character",
    )
    missing = [field for field in required if not planned_invocation.get(field)]
    if missing:
        raise ValueError(f"planned invocation lacks identity fields: {missing}")
    for name, value in (
        ("input_digest", input_digest),
        ("output_digest", output_digest),
    ):
        if (
            not isinstance(value, str)
            or not value.startswith("sha256:")
            or len(value) != 71
        ):
            raise ValueError(f"{name} must be a sha256 digest")
    mismatch = observed_execution_character != planned_invocation["execution_character"]
    receipt = {
        "schema_version": "bioagents.operation-invocation-receipt/v1",
        "polarity": "observed",
        **{field: planned_invocation[field] for field in required[:-1]},
        "planned_execution_character": planned_invocation["execution_character"],
        "observed_execution_character": observed_execution_character,
        "input_digest": input_digest,
        "output_digest": output_digest,
        "environment_identity": environment_identity,
        "status": "classification_mismatch" if mismatch else "observed",
        "blocking_reasons": (
            ["observed execution character differs from reviewed profile"]
            if mismatch
            else []
        ),
        "receipt_digest": "sha256:" + "0" * 64,
    }
    receipt["receipt_digest"] = _canonical_digest(receipt, "receipt_digest")
    return receipt


__all__ = [
    "BINDING_SCHEMA_VERSION",
    "PROFILE_SCHEMA_VERSION",
    "derive_skill_posture",
    "load_capability_profiles",
    "plan_profile_operations",
    "record_observed_invocation",
    "validate_capability_profile",
    "validate_runtime_binding",
    "verification_method_for",
]
