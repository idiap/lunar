# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0

"""Tests for Capability profiles.

This module protects expected behavior for the corresponding workflow, script, or repository surface. Key concepts: regression coverage, interface stability, and output integrity.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import jsonschema
import pytest

from lunar_planner.capability_profiles import (
    derive_skill_posture,
    load_capability_profiles,
    plan_profile_operations,
    record_observed_invocation,
    validate_capability_profile,
    validate_runtime_binding,
    verification_method_for,
)
from lunar_planner.config import resource_path

SKILL_DIGEST = "sha256:" + "1" * 64


def _digest(value: dict, field: str) -> str:
    """Digest."""
    payload = {key: item for key, item in value.items() if key != field}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(encoded.encode()).hexdigest()


def _operation(
    operation_id: str = "normalize-query",
    *,
    role: str = "exact_transform",
    character: str = "exact_deterministic",
    generation: str = "prohibited",
    binding_ids: tuple[str, ...] = ("binding.normalize",),
) -> dict:
    """Operation."""
    row = {
        "operation_id": operation_id,
        "purpose": "Perform the named bounded operation.",
        "reasoning_role": role,
        "execution_character": character,
        "generation_requirement": generation,
        "operation_role": "kernel",
        "inputs": [{"name": "request", "type": "Query", "required": True}],
        "outputs": [{"name": "result", "type": "NormalizedQuery", "required": True}],
        "failure_states": ["invalid_input", "unavailable_binding"],
        "epistemic_class": "derived",
        "epistemic_ceiling": "deterministic transform of supplied input",
        "verification": ["exact_comparison"],
        "abstention": ["invalid_input", "unavailable_binding"],
        "runtime_binding_ids": list(binding_ids),
        "binding_status": "bound" if binding_ids else "unavailable",
        "field_provenance": {
            "reasoning_role": {"source": "author", "evidence": "reviewed contract"},
            "execution_character": {
                "source": "runtime_observation",
                "evidence": "replay fixture",
            },
            "generation_requirement": {"source": "author"},
        },
    }
    if generation in {"required", "conditional"}:
        row["generative_controls"] = {
            "allowed_evidence_classes": ["retrieved"],
            "source_identity_required": True,
            "source_digests_required": True,
            "model_memory_as_evidence_allowed": False,
            "extraction_rules": ["preserve quotations and identifiers"],
            "freshness_rule": "use the reviewed evidence snapshot",
            "prompt_template_digest_required": True,
            "provider_provenance_required": True,
            "independent_verifier_required": True,
            "producer_may_self_approve": False,
            "structured_abstention_required": True,
            "expected_receipt_schema": "lunar.planner.generative-transformation-receipt/v1",
        }
    return row


def _profile(
    *operations: dict, authority: dict | None = None, reviewed: bool = True
) -> dict:
    """Profile."""
    value = {
        "schema_version": "bioagents.skill-capability-profile/v1",
        "skill_id": "scientific:asco-publication-search",
        "skill_digest": SKILL_DIGEST,
        "review_status": "reviewed" if reviewed else "draft",
        "reviewed_by": ["catalog-maintainer"] if reviewed else [],
        "operations": list(operations or (_operation(),)),
        "derived_posture": derive_skill_posture(list(operations or (_operation(),))),
        "authority": authority or {"approval": "human"},
        "capability_profile_digest": "sha256:" + "0" * 64,
    }
    value["capability_profile_digest"] = _digest(value, "capability_profile_digest")
    return value


def _binding(
    operation_id: str = "normalize-query",
    binding_id: str = "binding.normalize",
    *,
    kind: str = "package_local",
    available: bool = True,
) -> dict:
    """Binding."""
    value = {
        "schema_version": "bioagents.runtime-binding/v1",
        "binding_id": binding_id,
        "skill_id": "scientific:asco-publication-search",
        "operation_id": operation_id,
        "binding_kind": kind,
        "entrypoint": (
            None
            if kind == "unavailable"
            else {"protocol": "python", "locator": "pkg.module", "callable": "run"}
        ),
        "source_digest": "sha256:" + "2" * 64,
        "version": "1.0.0",
        "environment": {"lock_digest": "sha256:" + "3" * 64},
        "availability": {
            "status": "available" if available else "unavailable",
            "checked": True,
            "reason": "preflight metadata",
        },
        "permissions": [],
        "privacy_boundary": "repository",
        "network_required": False,
        "reproducibility": {
            "execution_character": "exact_deterministic",
            "seed": None,
            "tolerance": None,
            "nondeterminism": "none",
        },
        "license": {"spdx": "Apache-2.0", "redistribution": "allowed"},
        "fallback": {"mode": "explicit_unavailable" if not available else "none"},
        "invalidation": ["source_digest_change"],
        "binding_digest": "sha256:" + "0" * 64,
    }
    value["binding_digest"] = _digest(value, "binding_digest")
    return value


def test_profile_contract_is_operation_level_and_authority_independent() -> None:
    """Verify profile contract is operation level and authority independent."""
    deterministic = _profile(_operation(), authority={"approval": "human"})
    automatic = _profile(_operation(), authority={"approval": "automatic"})
    assert validate_capability_profile(deterministic) == ()
    assert validate_capability_profile(automatic) == ()
    assert (
        deterministic["derived_posture"]
        == automatic["derived_posture"]
        == "deterministic"
    )


def test_profile_forward_compatibility_is_confined_to_extensions() -> None:
    """Verify profile forward compatibility is confined to extensions."""
    profile = _profile(_operation())
    profile["extensions"] = {"future-taxonomy/v2": {"candidate": True}}
    profile["capability_profile_digest"] = _digest(profile, "capability_profile_digest")
    assert validate_capability_profile(profile) == ()
    profile["future_field"] = True
    profile["capability_profile_digest"] = _digest(profile, "capability_profile_digest")
    assert any(
        "Additional properties" in error
        for error in validate_capability_profile(profile)
    )


def test_hybrid_profile_requires_bounded_generation_controls() -> None:
    """Verify hybrid profile requires bounded generation controls."""
    generated = _operation(
        "interpret-results",
        role="semantic_generation",
        character="semantic_generative",
        generation="required",
        binding_ids=("binding.interpret",),
    )
    generated["verification"] = ["evidence_fidelity"]
    profile = _profile(_operation(), generated)
    assert profile["derived_posture"] == "hybrid"
    assert validate_capability_profile(profile) == ()
    del generated["generative_controls"]
    profile = _profile(_operation(), generated)
    assert any(
        "needs generative_controls" in error
        for error in validate_capability_profile(profile)
    )


def test_optional_presentation_does_not_make_the_essential_skill_hybrid() -> None:
    """Verify optional presentation does not make the essential skill hybrid."""
    presentation = _operation(
        "explain",
        role="semantic_generation",
        character="semantic_generative",
        generation="optional_presentation",
        binding_ids=("binding.explain",),
    )
    presentation["operation_role"] = "presentation"
    presentation["verification"] = ["evidence_fidelity"]
    profile = _profile(_operation(), presentation)
    assert profile["derived_posture"] == "deterministic"
    assert validate_capability_profile(profile) == ()


def test_required_semantic_plus_human_or_orchestration_is_hybrid() -> None:
    """Verify required semantic plus human or orchestration is hybrid."""
    generated = _operation(
        "propose",
        role="semantic_generation",
        character="semantic_generative",
        generation="required",
        binding_ids=("binding.propose",),
    )
    generated["verification"] = ["evidence_fidelity"]
    human = _operation(
        "approve",
        role="human_judgment",
        character="human_variable",
        generation="not_applicable",
        binding_ids=(),
    )
    human["verification"] = ["human_review"]
    assert derive_skill_posture([generated, human]) == "hybrid"


def test_profile_digest_duplicate_operations_and_stale_loader_fail_closed(
    tmp_path: Path,
) -> None:
    """Verify profile digest duplicate operations and stale loader fail closed."""
    profile = _profile(_operation(), deepcopy(_operation()))
    assert any("unique" in error for error in validate_capability_profile(profile))
    valid = _profile(_operation())
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(valid), encoding="utf-8")
    with pytest.raises(ValueError, match="stale skill_digest"):
        load_capability_profiles(
            [path], skill_digests={valid["skill_id"]: "sha256:" + "9" * 64}
        )


def test_computational_claim_needs_binding_or_explicit_unavailability() -> None:
    """Verify computational claim needs binding or explicit unavailability."""
    operation = _operation(binding_ids=())
    operation.pop("binding_status")
    profile = _profile(operation)
    assert any(
        "needs a binding or explicit unavailable" in error
        for error in validate_capability_profile(profile)
    )
    operation["binding_status"] = "unavailable"
    profile = _profile(operation)
    assert validate_capability_profile(profile) == ()


def test_prism_cannot_be_an_authoritative_profile_source(tmp_path: Path) -> None:
    """Verify prism cannot be an authoritative profile source."""
    prism = tmp_path / "prism_project"
    prism.mkdir()
    with pytest.raises(ValueError, match="Prism is not an authoritative"):
        load_capability_profiles([prism])


def test_runtime_binding_contract_represents_local_external_and_unavailable() -> None:
    """Verify runtime binding contract represents local external and unavailable."""
    assert validate_runtime_binding(_binding()) == ()
    external = _binding(kind="external_provider")
    external["entrypoint"] = {
        "protocol": "http",
        "locator": "https://provider.invalid/api",
    }
    external["network_required"] = True
    external["privacy_boundary"] = "external"
    external["reproducibility"]["execution_character"] = "provider_opaque"
    external["binding_digest"] = _digest(external, "binding_digest")
    assert validate_runtime_binding(external) == ()
    unavailable = _binding(kind="unavailable", available=False)
    assert validate_runtime_binding(unavailable) == ()


class _Registry:
    """Represent registry."""

    def __init__(self, bindings: dict[str, dict]) -> None:
        """Initialize registry."""
        self.bindings = bindings
        self.calls: list[tuple[str, str]] = []

    def resolve(self, logical_id: str, operation: str) -> dict | None:
        """Resolve."""
        self.calls.append((logical_id, operation))
        return self.bindings.get(operation)


def test_planner_consumes_reviewed_profile_through_existing_registry_without_execution() -> (
    None
):
    """Verify planner consumes reviewed profile through existing registry without execution."""
    second = _operation("retrieve", role="retrieval", binding_ids=("binding.retrieve",))
    profile = _profile(_operation(), second)
    registry = _Registry(
        {
            "normalize-query": _binding(),
            "retrieve": _binding("retrieve", "binding.retrieve", available=False),
        }
    )
    result = plan_profile_operations(
        profile["skill_id"], SKILL_DIGEST, {profile["skill_id"]: profile}, registry
    )
    assert result["status"] == "degraded"
    assert result["executed"] is False
    assert result["invocations"][0]["operation_id"] == "normalize-query"
    assert (
        result["invocations"][0]["capability_profile_digest"]
        == profile["capability_profile_digest"]
    )
    assert result["invocations"][0]["observed_receipt"] is None
    assert result["tasks"][0]["kind"] == "binding_unavailable"
    assert (
        "semantic generation is not a substitute" in result["tasks"][0]["remediation"]
    )
    assert registry.calls == [
        (profile["skill_id"], "normalize-query"),
        (profile["skill_id"], "retrieve"),
    ]


def test_unreviewed_profile_is_advisory_and_missing_operation_is_honest() -> None:
    """Verify unreviewed profile is advisory and missing operation is honest."""
    draft = _profile(_operation(), reviewed=False)
    result = plan_profile_operations(
        draft["skill_id"], SKILL_DIGEST, {draft["skill_id"]: draft}, _Registry({})
    )
    assert result["status"] == "advisory"
    reviewed = _profile(_operation())
    result = plan_profile_operations(
        reviewed["skill_id"],
        SKILL_DIGEST,
        {reviewed["skill_id"]: reviewed},
        _Registry({}),
        operation_ids=["not-there"],
    )
    assert result["tasks"] == [
        {
            "kind": "not_implemented",
            "operation_id": "not-there",
            "reason": "operation is absent from reviewed profile",
        }
    ]


def test_registry_lookup_failure_becomes_visible_unavailability() -> None:
    """Verify registry lookup failure becomes visible unavailability."""

    class RaisingRegistry:
        """Represent raising registry."""

        def resolve(self, logical_id: str, operation: str) -> None:
            """Resolve."""
            raise LookupError(f"no binding for {logical_id}:{operation}")

    profile = _profile(_operation())
    result = plan_profile_operations(
        profile["skill_id"],
        SKILL_DIGEST,
        {profile["skill_id"]: profile},
        RaisingRegistry(),
    )
    assert result["status"] == "blocked"
    assert result["tasks"][0]["kind"] == "binding_unavailable"
    assert "no binding" in result["tasks"][0]["reason"]


def test_observed_receipt_is_separate_and_preserves_invocation_identity() -> None:
    """Verify observed receipt is separate and preserves invocation identity."""
    profile = _profile(_operation())
    registry = _Registry({"normalize-query": _binding()})
    plan = plan_profile_operations(
        profile["skill_id"], SKILL_DIGEST, {profile["skill_id"]: profile}, registry
    )
    receipt = record_observed_invocation(
        plan["invocations"][0],
        input_digest="sha256:" + "a" * 64,
        output_digest="sha256:" + "b" * 64,
        environment_identity="python:3.13;lock:sha256:fixture",
        observed_execution_character="exact_deterministic",
    )
    assert receipt["polarity"] == "observed"
    assert receipt["status"] == "observed"
    assert receipt["operation_id"] == "normalize-query"
    assert receipt["capability_profile_digest"] == profile["capability_profile_digest"]
    assert plan["invocations"][0]["observed_receipt"] is None


def test_observed_execution_character_mismatch_blocks_claim() -> None:
    """Verify observed execution character mismatch blocks claim."""
    planned = {
        "skill_id": "s",
        "skill_digest": SKILL_DIGEST,
        "operation_id": "op",
        "capability_profile_digest": "sha256:" + "2" * 64,
        "binding_id": "binding",
        "binding_digest": "sha256:" + "3" * 64,
        "execution_character": "exact_deterministic",
    }
    receipt = record_observed_invocation(
        planned,
        input_digest="sha256:" + "a" * 64,
        output_digest="sha256:" + "b" * 64,
        environment_identity="opaque-provider",
        observed_execution_character="provider_opaque",
    )
    assert receipt["status"] == "classification_mismatch"
    assert receipt["blocking_reasons"]


@pytest.mark.parametrize(
    ("character", "expected"),
    [
        ("exact_deterministic", "exact_comparison"),
        ("numerically_deterministic", "tolerance_check"),
        ("seeded_stochastic", "statistical_diagnostics"),
        ("stochastic_estimated", "statistical_diagnostics"),
        ("provider_opaque", "evidence_fidelity"),
        ("semantic_generative", "evidence_fidelity"),
        ("human_variable", "human_review"),
        ("non_executing", "availability_only"),
    ],
)
def test_verification_is_selected_from_execution_character(
    character: str, expected: str
) -> None:
    """Verify verification is selected from execution character."""
    assert expected in verification_method_for(
        {"execution_character": character, "verification": []}
    )


def test_post_plan_adapter_coverage_has_no_global_count_minimum() -> None:
    """Verify post plan adapter coverage has no global count minimum."""
    schema = json.loads(
        resource_path(
            "schemas", "planner-post-plan-evidence-verification-v1.schema.json"
        ).read_text()
    )
    adapter_schema = schema["properties"]["deterministic_adapter_contracts"]
    jsonschema.Draft202012Validator.check_schema(schema)
    assert "minItems" not in adapter_schema
