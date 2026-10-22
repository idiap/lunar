# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Planning-only lifecycle over an explicitly selected host capability snapshot."""

from __future__ import annotations
import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from .archetypes import build_archetype_index, load_surface_index, match_archetypes
from .delivery_package import plan_delivery_package
from .next_steps import build_next_step_guidance
from .policy import build_report_workflow_inheritance, policy_value
from .ports import build_invocation_plan, current_ports

SCHEMA_VERSION = "lunar.planner.routing-decision/v1"
PROFILE_BY_MODE = {
    "direct_use": "planner-resource://profiles/direct-use.yaml",
    "new_workflow": "planner-resource://profiles/new-workflow.yaml",
    "extend_existing_workflow": "planner-resource://profiles/extend-workflow.yaml",
    "refine_output_problem": "planner-resource://profiles/refine-workflow.yaml",
}
FORBIDDEN_ROUTE_ONLY_AUTHORITIES = {
    "execute",
    "execution",
    "external_actions",
    "goal_creation",
    "install",
    "network",
}


def _normalized(value: str) -> str:
    """Normalized."""
    return re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")


def _canonical_digest(value: Any) -> str:
    """Canonical digest."""
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def _candidate_target_phrases(command_text: str, references: Iterable[str]) -> set[str]:
    # References identify context, artifacts, or workflows to inspect; they are
    # not themselves a direct-use request.  Only the command can select the
    # direct route.  Consume the iterable to keep the helper's boundary explicit.
    """Candidate target phrases."""
    tuple(references)
    values: set[str] = set()
    text = command_text.strip().strip("`'\"")
    values.add(_normalized(text))
    direct = re.fullmatch(
        r"(?i)\s*(?:please\s+)?(?:use|run|invoke|route\s+to)\s+[`'\"]?(.+?)[`'\"]?\s*[.!]?\s*",
        text,
    )
    if direct:
        values.add(_normalized(direct.group(1)))
    return {value for value in values if value}


def _surface_candidates(index: Mapping[str, Any], query: str) -> list[dict[str, Any]]:
    """Gather workflow-level candidates before any leaf-skill lookup."""

    tokens = set(re.findall(r"[a-z0-9]+", query.casefold()))
    rows: list[tuple[int, str, Mapping[str, Any]]] = []
    for priority, collection in enumerate(
        (index.get("workflow_packages", ()), index.get("subworkflows", ()))
    ):
        for row in collection:
            if not row.get("available", False):
                continue
            identity_text = " ".join(
                [
                    str(row.get("id", "")),
                    str(row.get("canonical_id", "")),
                    str(row.get("display_name", "")),
                    *(str(alias) for alias in row.get("aliases", ())),
                ]
            )
            identity = set(re.findall(r"[a-z0-9]+", identity_text.casefold()))
            description = set(
                re.findall(
                    r"[a-z0-9]+",
                    str(row.get("description", row.get("purpose", ""))).casefold(),
                )
            )
            score = 4 * len(tokens & identity) + len(tokens & description)
            if score:
                rows.append((score, f"{priority}:{row['id']}", row))
    rows.sort(key=lambda item: (-item[0], item[1]))
    return [
        {
            "id": row["id"],
            "kind": row["kind"],
            "source_path": row["source_path"],
            "available": True,
            "score": score,
            "requires_full_contract_review": True,
            "canonical_id": row.get("canonical_id"),
            "display_name": row.get("display_name"),
            "control": row.get("control"),
            "content_digest": row.get("content_digest"),
            "report_control_blueprint": row.get("report_control_blueprint"),
        }
        for score, _sort_key, row in rows[:5]
    ]


def _exact_surface(
    index: Mapping[str, Any], phrases: set[str]
) -> dict[str, Any] | None:
    """Resolve exact workflow/subworkflow identity before leaf skills."""

    for collection in (
        index.get("workflow_packages", ()),
        index.get("subworkflows", ()),
    ):
        for row in collection:
            identities = {
                _normalized(str(row.get("id", ""))),
                _normalized(str(row.get("canonical_id", ""))),
                _normalized(str(row.get("display_name", ""))),
                *(_normalized(str(alias)) for alias in row.get("aliases", ())),
            }
            if row.get("available", False) and phrases.intersection(identities):
                return dict(row)
    return None


def _reference_surface(
    index: Mapping[str, Any], references: Iterable[str]
) -> dict[str, Any] | None:
    """Reference surface."""
    phrases = {_normalized(value) for value in references}
    return _exact_surface(index, phrases)


def _requested_forbidden_authority(
    execution_mode: str, authority_envelope: Mapping[str, Any]
) -> list[str]:
    """Requested forbidden authority."""
    reasons: list[str] = []
    if execution_mode != "route_only":
        reasons.append("only execution_mode='route_only' is supported")
    if authority_envelope.get("allow_route_only") is False:
        reasons.append("route-only planning authority was denied")
    if authority_envelope.get("mode", "planning_only") != "planning_only":
        reasons.append("authority mode must remain planning_only")
    for field in ("execution", "external_actions", "mutation"):
        value = authority_envelope.get(field, "forbidden")
        if value != "forbidden":
            reasons.append(f"authority {field} must remain forbidden")
    requested = {
        _normalized(str(item))
        for item in authority_envelope.get("requested_permissions", ())
    }
    requested.update(
        key
        for key in FORBIDDEN_ROUTE_ONLY_AUTHORITIES
        if authority_envelope.get(key) is True
    )
    forbidden = sorted(requested & FORBIDDEN_ROUTE_ONLY_AUTHORITIES)
    if forbidden:
        reasons.append("route-only boundary forbids: " + ", ".join(forbidden))
    return reasons


def _base_result(command_text: str, mode: str, primary_intent: str) -> dict[str, Any]:
    """Base result."""
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "ready_for_semantic_review",
        "mode": mode,
        "primary_intent": primary_intent,
        "command_text": command_text,
        "route_only": True,
        "executed": False,
        "performed_actions": [],
        "execution_allowed": False,
        "external_actions_allowed": False,
        "network_allowed": False,
        "installation_allowed": False,
        "codex_subprocess_allowed": False,
        "goal_creation_allowed": False,
        "semantic_review_required": True,
        "selection_boundary": (
            "This result gathers and orders planning candidates only; it neither proves "
            "semantic fit nor executes any capability."
        ),
    }


def _run_legacy_planner_request(
    command_text: str,
    references: Iterable[str] | None = None,
    authority_envelope: Mapping[str, Any] | None = None,
    execution_mode: str = "route_only",
    active_plan_id: str | None = None,
    codex_control: Mapping[str, Any] | None = None,
    *,
    desired_inputs: Iterable[str] = (),
    desired_outputs: Iterable[str] = (),
    scope: str = "package",
    repo_root: Path | str | None = None,
    surface_index: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Classify one request and return a non-executing planner handoff."""

    del codex_control  # Goal/control integration is intentionally unsupported here.
    refs = tuple(str(item) for item in (references or ()))
    envelope = dict(authority_envelope or {})
    denial_reasons = _requested_forbidden_authority(execution_mode, envelope)
    if denial_reasons:
        result = _base_result(
            command_text, "insufficient_context", "insufficient_context"
        )
        result.update(status="denied", blockers=denial_reasons, profile=None)
        return result

    index = dict(surface_index or load_surface_index(repo_root=repo_root))
    phrases = _candidate_target_phrases(command_text, refs)
    lowered = command_text.casefold()

    if re.search(
        r"\b(?:inspect|show|trace)\b(?:\s+(?:the|this|run|result|component|skill|artifact)){0,4}\s+\b(?:provenance|lineage)\b"
        r"|\b(?:which skill|what)\b[^?.]{0,40}\bproduced\b",
        lowered,
    ):
        result = _base_result(command_text, "inspect_provenance", "inspect_provenance")
        if not refs and not active_plan_id:
            result.update(
                status="needs_input",
                blockers=[
                    "an authorized run, result, or component reference is required"
                ],
            )
        result.update(profile=None, lookup_only=True, references=list(refs))
        return result

    if re.search(r"\b(resume|continue)\b", lowered):
        result = _base_result(command_text, "resume_plan", "resume_plan")
        if not active_plan_id:
            result.update(status="needs_input", blockers=["active_plan_id is required"])
        result.update(
            profile=None, active_plan_id=active_plan_id, state_lookup_required=True
        )
        return result

    exact = _exact_surface(index, phrases)
    if exact is not None:
        result = _base_result(command_text, "direct_use", "direct_workflow_run")
        result.update(
            profile=PROFILE_BY_MODE["direct_use"],
            selected_target={
                "id": exact["id"],
                "canonical_id": exact.get("canonical_id", exact["id"]),
                "display_name": exact.get("display_name"),
                "kind": exact["kind"],
                "source_path": exact["source_path"],
                "operations": exact.get("operations"),
                "hooks": exact.get("hooks"),
                "control": exact.get("control"),
                "controlled_invocation_entrypoint": (exact.get("control") or {}).get(
                    "planner_entrypoint"
                ),
                "execution_posture": exact.get("execution_posture"),
            },
            candidate_cascade=["exact_workflow_or_subworkflow"],
        )
        return result

    if re.fullmatch(
        r"\s*(?:help|list|show)(?:\s+(?:skills|workflows|capabilities))?[?.!]?\s*",
        lowered,
    ):
        result = _base_result(command_text, "capability_help", "capability_help")
        result.update(
            status="complete",
            profile=None,
            counts=dict(index.get("counts", {})),
            workflow_packages=list(index.get("workflow_packages", ())),
            subworkflows=list(index.get("subworkflows", ())),
            semantic_review_required=False,
        )
        return result

    referenced_workflow = _reference_surface(index, refs)

    workflow_candidates = _surface_candidates(index, command_text)
    if referenced_workflow is not None:
        workflow_candidates = [
            {
                **referenced_workflow,
                "score": 100,
                "rationale": ["explicit workflow reference"],
            }
        ]
    skills = list(index.get("skills", ()))
    exact_skills = [
        row
        for row in skills
        if _normalized(str(row.get("name", row.get("id", "")))) in phrases
    ]
    description_skills = [
        row
        for row in skills
        if (description := _normalized(str(row.get("description", ""))))
        and description in _normalized(command_text)
    ]
    direct_skills = exact_skills or description_skills
    if direct_skills:
        skill = dict(direct_skills[0])
        skill_id = skill.get("id", skill.get("name"))
        if not isinstance(skill_id, str) or not skill_id:
            raise ValueError("selected skill is missing a valid id")
        skill["id"] = skill_id
        result = _base_result(command_text, "direct_use", "direct_skill_use")
        result.update(
            profile=PROFILE_BY_MODE["direct_use"],
            selected_target=skill,
            candidate_cascade=[
                "exact_workflow_or_subworkflow",
                (
                    "exact_leaf_skill"
                    if exact_skills
                    else "documented_leaf_skill_description"
                ),
            ],
        )
        if current_ports().invocation_router is not None:
            invocation = build_invocation_plan(
                [skill_id], scope=scope, request={"command_text": command_text}
            )
            result["invocation_plan"] = invocation
            denied = set(envelope.get("denied_permissions", ())) & set(
                invocation.get("aggregated_authority", {}).get("permissions", ())
            )
            if denied:
                result.update(
                    status="denied",
                    blockers=[
                        "authority envelope denies required permissions: "
                        + ", ".join(sorted(denied))
                    ],
                )
            elif invocation.get("status") == "blocked":
                result.update(
                    status="blocked", blockers=list(invocation.get("blockers", ()))
                )
        return result
    requested = " ".join((command_text, *desired_inputs, *desired_outputs)).casefold()
    referenced = bool(refs) or bool(workflow_candidates)
    if referenced and re.search(r"\b(add|extend|augment|append|enhance)\b", requested):
        mode = "extend_existing_workflow"
    elif referenced and re.search(
        r"\b(revise|clarify|correct|fix|repair|wrong|incorrect|broken|refine)\b",
        requested,
    ):
        mode = "refine_output_problem"
    elif re.search(r"\b(new workflow|create|build|design|compose)\b", lowered):
        mode = "new_workflow"
    else:
        mode = "insufficient_context"
    result = _base_result(command_text, mode, mode)
    result.update(
        profile=PROFILE_BY_MODE.get(mode),
        references=list(refs),
        candidates={
            "workflow_first": workflow_candidates,
            "uncovered_archetypes": match_archetypes(
                command_text, build_archetype_index(index)
            ),
            "leaf_skills": [],
        },
        candidate_cascade=[
            "exact_workflow_or_subworkflow",
            "uncovered_reusable_archetype",
            "leaf_skill_candidates",
        ],
        resource_scan={
            "snapshot_posture": "host_surface_only",
            "snapshot_digest": "sha256:" + _canonical_digest(index),
            "counts": dict(index.get("counts", {})),
        },
    )
    if mode == "insufficient_context":
        result.update(
            status="needs_input",
            blockers=[
                "state the desired output and whether to use, extend, refine, or design"
            ],
        )
    else:
        result.update(reuse_first=True, custom_implementation_allowed=False)
    package_policy = (
        policy_value(
            "request",
            {
                "command_text": command_text,
                "surface": index,
                "references": refs,
                "desired_inputs": tuple(desired_inputs),
                "desired_outputs": tuple(desired_outputs),
                "authority": envelope,
            },
            {},
        )
        or {}
    )
    if not isinstance(package_policy, Mapping):
        raise ValueError("invalid package request policy")
    result["domain_policy"] = dict(package_policy)
    override = package_policy.get("routing_override")
    if isinstance(override, Mapping):
        if override.get("mode") not in PROFILE_BY_MODE:
            raise ValueError("unsupported package routing disposition")
        result.update(
            mode=override["mode"],
            primary_intent=str(override.get("primary_intent", override["mode"])),
            profile=PROFILE_BY_MODE[override["mode"]],
        )
        if override.get("status") in {"blocked", "denied", "needs_input"}:
            result.update(
                status=override["status"], blockers=list(override.get("blockers", ()))
            )
    for key in (
        "external_source_plan",
        "external_capability_coverage",
        "provider_family_plan",
    ):
        if key in package_policy:
            result[key] = package_policy[key]
    return result


def run_planner_request(
    command_text: str,
    references: Iterable[str] | None = None,
    authority_envelope: Mapping[str, Any] | None = None,
    execution_mode: str = "route_only",
    active_plan_id: str | None = None,
    codex_control: Mapping[str, Any] | None = None,
    *,
    desired_inputs: Iterable[str] = (),
    desired_outputs: Iterable[str] = (),
    supplied_inputs: Mapping[str, Any] | None = None,
    continuation: Mapping[str, Any] | None = None,
    scope: str = "package",
    repo_root: Path | str | None = None,
    answer_trust_readiness_enabled: bool = False,
    answer_trust_rollout_state: str = "off",
    workflow_economics_enabled: bool = False,
    workflow_economics_mode: str = "off",
    workflow_economics_rollout_state: str = "off",
    workflow_economics_comparator: Mapping[str, Any] | None = None,
    workflow_economics_workload_manifest: Mapping[str, Any] | None = None,
    workflow_economics_resource_profile: Mapping[str, Any] | None = None,
    surface_index: Mapping[str, Any] | None = None,
    _validated_test_snapshot: bool = False,
) -> dict[str, Any]:
    """Return the compatible v1 decision plus a sealed staged receipt.

    ``surface_index`` is retained as a compatibility seam for repository tests;
    production callers should omit it.  It must still be a validated planner
    surface and is explicitly marked in the receipt.
    """

    if surface_index is None and current_ports().surface is None:
        result = _base_result(
            command_text, "insufficient_context", "insufficient_context"
        )
        result.update(
            status="selection_required",
            blockers=["Import and select a package version before planning"],
            planner_receipt={"disposition": "selection_required"},
        )
        return result

    if workflow_economics_mode not in {"off", "estimate", "observe", "budget"}:
        raise ValueError(
            "workflow_economics_mode must be off, estimate, observe, or budget"
        )
    if workflow_economics_mode in {"observe", "budget"}:
        raise ValueError(
            "observed economics and budget mutation require the explicit authorized "
            "host APIs; the planning-only entrypoint can produce estimates only"
        )

    if surface_index is not None and not _validated_test_snapshot:
        raise ValueError(
            "production planner rejects surface injection; use run_planner_request_with_test_surface"
        )
    if surface_index is not None and surface_index.get("schema_version") not in {
        "lunar.planner.surface-index/v1",
        "lunar.planner.surface-index/v2",
    }:
        raise ValueError("test surface must be a schema-validated planner surface")
    result = _run_legacy_planner_request(
        command_text,
        references=references,
        authority_envelope=authority_envelope,
        execution_mode=execution_mode,
        active_plan_id=active_plan_id,
        codex_control=codex_control,
        desired_inputs=desired_inputs,
        desired_outputs=desired_outputs,
        scope=scope,
        repo_root=repo_root,
        surface_index=surface_index,
    )
    result["delivery_package_policy"] = plan_delivery_package(
        command_text, desired_outputs=desired_outputs
    )
    index = dict(surface_index or load_surface_index(repo_root=repo_root))
    report_inheritance = build_report_workflow_inheritance(
        command_text,
        index,
        references=tuple(str(item) for item in (references or ())),
        desired_outputs=desired_outputs,
    )
    if report_inheritance is not None:
        result["report_workflow_inheritance"] = report_inheritance
    # Help, provenance lookup, resume, and authority denial are control-plane
    # dispositions rather than component semantic-routing requests.
    quality_continuation = bool(
        continuation and isinstance(continuation.get("quality_checkpoint"), Mapping)
    )
    if (
        result["mode"] in {"capability_help", "inspect_provenance", "resume_plan"}
        or result["status"] == "denied"
    ) and not quality_continuation:
        from .staged_routing import plan_control_request

        receipt = plan_control_request(
            command_text,
            mode=str(result["mode"]),
            status=str(result["status"]),
            references=tuple(str(item) for item in (references or ())),
            desired_inputs=desired_inputs,
            desired_outputs=desired_outputs,
            supplied_inputs=supplied_inputs,
            blockers=result.get("blockers", ()),
        )
        result["planner_receipt"] = receipt
        result["requirement_ledger"] = receipt["requirement_ledger"]
        result["quality_disposition"] = receipt["quality_disposition"]
        result["next_step_guidance"] = build_next_step_guidance(result)
        return result
    from .staged_routing import plan_stages

    # Package discovery is planning-only and is produced before the immutable
    # workflow is verified so the sidecar can bind every already-available
    # discovery receipt without performing retrieval itself.
    package_receipt = policy_value(
        "package_search",
        {
            "text": command_text,
            "surface": index,
            "desired_inputs": tuple(desired_inputs),
            "desired_outputs": tuple(desired_outputs),
        },
        {"status": "not_configured", "candidates": [], "executed": False},
    )
    verification_context = {
        key: value
        for key, value in {
            "external_source_plan": result.get("external_source_plan"),
            "external_capability_coverage": result.get("external_capability_coverage"),
            "package_search_receipt": package_receipt,
        }.items()
        if value is not None
    }
    selected_target = result.get("selected_target") or {}
    exact_route_hint = (
        str(selected_target.get("route") or selected_target.get("id"))
        if result.get("mode") == "direct_use"
        and (selected_target.get("route") or selected_target.get("id"))
        else None
    )
    if (
        exact_route_hint is None
        and result.get("primary_intent") == "external_data_query"
    ):
        source_plans = list(
            (result.get("external_source_plan") or {}).get("query_plans", ())
        )
        source_skill_ids = {
            str(plan.get("selected_skill_id"))
            for plan in source_plans
            if plan.get("selected_skill_id")
        }
        if len(source_skill_ids) == 1:
            exact_route_hint = source_skill_ids.pop()

    receipt = plan_stages(
        command_text,
        index,
        references=tuple(str(item) for item in (references or ())),
        desired_inputs=desired_inputs,
        desired_outputs=desired_outputs,
        supplied_inputs=supplied_inputs,
        authority_envelope=authority_envelope,
        continuation=continuation,
        exact_route_hint=exact_route_hint,
        routing_mode_hint=str(result.get("mode") or ""),
        verification_context=verification_context,
        answer_trust_readiness_enabled=answer_trust_readiness_enabled,
        answer_trust_rollout_state=answer_trust_rollout_state,
        workflow_economics_enabled=workflow_economics_enabled,
        workflow_economics_mode=workflow_economics_mode,
        workflow_economics_rollout_state=workflow_economics_rollout_state,
        workflow_economics_comparator=workflow_economics_comparator,
        workflow_economics_workload_manifest=workflow_economics_workload_manifest,
        workflow_economics_resource_profile=workflow_economics_resource_profile,
        test_snapshot=surface_index is not None,
    )
    if "package_search_receipt" not in receipt:
        receipt["package_search_receipt"] = package_receipt
        receipt["digest"] = "sha256:" + _canonical_digest(
            {key: value for key, value in receipt.items() if key != "digest"}
        )
    result["planner_receipt"] = receipt
    result["selected_targets"] = receipt.get("selected_targets", [])
    result["dialogue_state"] = receipt.get("dialogue_state")
    result["requirement_ledger"] = receipt.get("requirement_ledger")
    result["workflow_draft"] = receipt.get("workflow_draft")
    result["workflow_instantiation"] = receipt.get("workflow_instantiation")
    result["proposed_skill_test_plans"] = receipt.get("proposed_skill_test_plans", [])
    if "post_plan_evidence_verification" in receipt:
        result["post_plan_evidence_verification"] = receipt[
            "post_plan_evidence_verification"
        ]
    if "answer_control_readiness" in receipt:
        result["answer_control_readiness"] = receipt["answer_control_readiness"]
    if "answer_control_readiness_card" in receipt:
        result["answer_control_readiness_card"] = receipt[
            "answer_control_readiness_card"
        ]
    for economics_key in (
        "workflow_workload_inventory",
        "workflow_effort_estimate",
        "workflow_resource_estimate",
        "workflow_effort_card",
        "workflow_economics_report",
    ):
        if economics_key in receipt:
            result[economics_key] = receipt[economics_key]
    result["workflow_refinement_cycle"] = receipt.get("workflow_refinement_cycle")
    result["reasoning_log"] = receipt.get("reasoning_log")
    result["reasoning_log_markdown"] = receipt.get("reasoning_log_markdown")
    result["package_search_receipt"] = package_receipt
    execution_target = (receipt.get("dialogue_state") or {}).get("execution_target")
    locked_target = (receipt.get("delivery_handoff") or {}).get("selected_target", {})
    if (
        receipt.get("disposition") == "ready_for_delivery"
        and execution_target
        and execution_target.get("bound_reader_id") == locked_target.get("id")
    ):
        result["execution_target"] = dict(execution_target)
    if quality_continuation:
        entrypoint_mode = receipt.get("dialogue_state", {}).get("entrypoint_mode")
        if entrypoint_mode:
            result["mode"] = entrypoint_mode
        if result.get("primary_intent") == "resume_plan":
            result["primary_intent"] = "quality_checkpoint_continuation"
        result.pop("active_plan_id", None)
        result.pop("state_lookup_required", None)
    if receipt.get("capability_gap_plan") is not None:
        result["capability_gap_plan"] = receipt["capability_gap_plan"]
    result["elicitation"] = {
        "disposition": receipt["disposition"],
        "continuation": receipt["continuation"],
        "questions": receipt.get("elicitation", {}).get("questions", []),
        "unresolved_question_ids": receipt.get("elicitation", {}).get(
            "unresolved_question_ids", []
        ),
        "repeated_question": receipt.get("elicitation", {}).get(
            "repeated_question", False
        ),
    }
    if receipt["disposition"] in {
        "quality_planning_required",
        "delivery_quality_planning_required",
    } and (quality_continuation or result.get("status") != "needs_input"):
        specialized_domain_route = bool(
            result.get("domain_policy", {}).get("routing_override")
        )
        if specialized_domain_route:
            # Preserve the v1 domain-planner route and status for callers that
            # consume these deterministic, zero-I/O plans.  The staged receipt
            # still exposes the mandatory quality checkpoint and withholds any
            # execution or delivery handoff.
            result["delivery_handoff"] = None
            result["quality_disposition"] = receipt["disposition"]
        else:
            result["status"] = "needs_quality_review"
            result["blockers"] = [receipt["disposition"]]
            result["delivery_handoff"] = None
            # The legacy exact-name resolver supplies a planner-owned identity hint,
            # but the public route remains unselected until the outcome freeze.
            result["selected_target"] = (
                receipt["adjudication"].get("selected")
                if receipt["disposition"] == "delivery_quality_planning_required"
                else None
            )
    # Complete implicit direct-use requests now graduate from candidate-only
    # fallback to a route-locked delivery handoff. Existing exact/change-route
    # fields remain unchanged for v1 consumers.
    frame_says_direct = not receipt["request_frame"]["persistent_change_requested"]
    if (
        quality_continuation
        or result["mode"] == "insufficient_context"
        or (result["mode"] == "new_workflow" and frame_says_direct)
    ) and receipt["disposition"] in {
        "ready_for_delivery",
        "clarification_required",
        "no_local_match",
        "contract_gap",
    }:
        if receipt["disposition"] == "ready_for_delivery":
            result.update(
                mode="direct_use",
                primary_intent="direct_component_use",
                status="ready_for_semantic_review",
                profile=PROFILE_BY_MODE["direct_use"],
                selected_target=receipt["adjudication"].get("selected"),
                delivery_handoff=receipt["delivery_handoff"],
                blockers=[],
            )
        elif receipt["disposition"] == "clarification_required":
            result.update(
                status="needs_input",
                blockers=[
                    "provide the material outcome-level fields in the continuation envelope"
                ],
            )
        elif receipt["disposition"] == "no_local_match":
            result.update(
                mode="no_local_match",
                primary_intent="no_local_match",
                status="no_local_match",
                profile=None,
                blockers=[receipt["adjudication"]["reason"]],
            )
    result["next_step_guidance"] = build_next_step_guidance(result)
    return result


def run_planner_request_with_test_surface(
    command_text: str,
    surface_index: Mapping[str, Any],
    **kwargs: Any,
) -> dict[str, Any]:
    """Explicit test seam for a schema-validated, receipt-marked snapshot."""

    return run_planner_request(
        command_text,
        surface_index=surface_index,
        _validated_test_snapshot=True,
        **kwargs,
    )


route_planner_request = run_planner_request
