# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0

"""Planner-owned semantic routing stages over a sealed component surface.

This module is deliberately route-only.  It frames a request, gathers a
bounded shortlist, adjudicates semantic fit, binds declared ports, performs
authority/availability preflight, and emits a content-addressed delivery
handoff.  It never loads skill instructions or executes a component.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from collections import Counter
from collections.abc import Iterable, Mapping, MutableMapping
from itertools import chain, pairwise
from typing import Any

from lunar_planner.contracts import (
    canonical_digest,
    seal_quality_contract,
    validate_contract,
)
from lunar_planner.answer_trust import (
    build_answer_control_readiness,
    build_readiness_card,
    resolve_answer_trust_rollout,
)
from lunar_planner.post_plan_verification import build_post_plan_verification
from lunar_planner.usage_accounting import estimate_workflow_resources
from lunar_planner.workflow_economics import (
    build_workflow_economics_report,
    build_workflow_effort_card,
    compile_work_units,
    estimate_workflow_effort,
    resolve_workflow_economics_rollout,
)
from lunar_planner.quality_attestation import (
    verify_signed_quality_receipt,
)
from lunar_planner.quality_evaluation import (
    plan_review_evaluation_receipts_sufficient,
)
from lunar_planner.quality_governance import (
    classify_quality_policy,
    material_quality_elicitation,
    normalize_consequence_profile,
    update_quality_question_states,
)
from lunar_planner.policy import (
    build_report_workflow_inheritance,
    project_report_inheritance_plans,
)

from .config import current_config
from .policy import policy_value
from .reasoning_log import build_reasoning_log, render_reasoning_log_markdown

RECEIPT_SCHEMA = "lunar.planner.staged-receipt/v1"
FRAME_SCHEMA = "lunar.planner.request-frame/v1"
HANDOFF_SCHEMA = "lunar.planner.delivery-handoff/v1"
CONTINUATION_SCHEMA = "lunar.planner.continuation/v1"
DIALOGUE_STATE_SCHEMA = "lunar.planner.dialogue-state/v1"
REQUIREMENT_LEDGER_SCHEMA = "lunar.planner.requirement-ledger/v1"
WORKFLOW_DRAFT_SCHEMA = "lunar.planner.workflow-draft/v1"
WORKFLOW_INSTANTIATION_SCHEMA = "lunar.planner.workflow-instantiation/v1"
SKILL_TEST_PLAN_SCHEMA = "lunar.planner.proposed-skill-test-plan/v1"
WORKFLOW_REFINEMENT_SCHEMA = "lunar.planner.workflow-refinement-cycle/v1"
ELICITATION_SCHEMA = "lunar.planner.elicitation/v1"
OUTCOME_QUALITY_SCHEMA = "lunar.planner.contextual-outcome-quality-contract/v1"
DELIVERY_QUALITY_SCHEMA = "lunar.planner.route-delivery-quality-plan/v1"
QUALITY_REVIEW_SCHEMA = "lunar.planner.quality-plan-review/v1"
QUALITY_ASSESSMENT_SCHEMA = "lunar.planner.quality-assessment/v1"
FINAL_DECISION_SCHEMA = "lunar.planner.final-delivery-decision/v1"
QUALITY_CRITERION_SCHEMA = "lunar.planner.contextual-quality-criterion/v1"
FAILURE_OWNERS = {
    "understanding",
    "retrieval",
    "adjudication",
    "binding",
    "preflight",
    "dispatch",
}
GAP_CLASSES = {"universal", "project_specific", "adapter", "workflow_local"}

_STOP = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "before",
    "by",
    "can",
    "do",
    "each",
    "for",
    "from",
    "give",
    "have",
    "i",
    "in",
    "into",
    "is",
    "it",
    "make",
    "me",
    "my",
    "non",
    "of",
    "on",
    "or",
    "our",
    "please",
    "rather",
    "remain",
    "that",
    "the",
    "their",
    "these",
    "this",
    "to",
    "using",
    "want",
    "we",
    "than",
    "what",
    "while",
    "with",
    "without",
}
_TASK_TERMS = {
    "build",
    "check",
    "compose",
    "create",
    "design",
    "explain",
    "find",
    "four",
    "generate",
    "make",
    "part",
    "plan",
    "review",
    "run",
    "someth",
    "something",
    "string",
    "use",
    "write",
}
_SEMANTIC_STEMS = {
    "accept": "check",
    "accepted": "check",
    "acceptance": "check",
    "conditional": "claim",
    "complet": "result",
    "comput": "result",
    "computation": "result",
    "critique": "critic",
    "criticism": "critic",
    "explanation": "explain",
    "explainer": "explain",
    "verification": "verify",
    "verifier": "verify",
    "interpretation": "interpret",
    "interpreter": "interpret",
    "formally": "formal",
    "kernel": "check",
    "proposition": "claim",
    "render": "explain",
    "translate": "explain",
}


def _digest(value: Any) -> str:
    """Digest."""
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return "sha256:" + hashlib.sha256(payload.encode()).hexdigest()


def _tokens(value: Any) -> list[str]:
    """Tokens."""
    text = json.dumps(value, sort_keys=True) if not isinstance(value, str) else value
    words = re.findall(r"[a-z0-9]+", text.casefold())
    result: list[str] = []
    for word in words:
        if word in _STOP or len(word) < 3:
            continue
        # Conservative morphology makes lexical retrieval less dependent on
        # grammatical register while retaining biomedical terms.
        for suffix in ("ization", "isation", "ments", "ing", "ed", "es", "s"):
            if word.endswith(suffix) and len(word) - len(suffix) >= 4:
                word = word[: -len(suffix)]
                break
        result.append(_SEMANTIC_STEMS[word] if word in _SEMANTIC_STEMS else word)
    return result


def _features(value: Any) -> list[str]:
    """Return normalized terms plus local phrase features for sibling contrast."""

    terms = _tokens(value)
    phrases = [f"{left}::{right}" for left, right in pairwise(terms)]
    return terms + phrases


def _document(row: Mapping[str, Any], lane: str) -> Any:
    """Document."""
    if lane == "identity":
        return [row.get("id"), row.get("name"), row.get("aliases", [])]
    if lane == "purpose":
        return [row.get("description"), row.get("purpose"), row.get("triggers")]
    if lane == "input":
        return [
            row.get("inputs"),
            row.get("interface", {}).get("inputs"),
            row.get("routing_interface", {}).get("inputs"),
        ]
    if lane == "output":
        return [
            row.get("outputs"),
            row.get("terminals"),
            row.get("interface", {}).get("outputs"),
            row.get("routing_interface", {}).get("outputs"),
        ]
    if lane == "boundary":
        return [row.get("non_triggers"), row.get("non_goals"), row.get("gates")]
    return row


def normalize_request(
    command_text: str,
    *,
    references: Iterable[str] = (),
    desired_inputs: Iterable[str] = (),
    desired_outputs: Iterable[str] = (),
    supplied_inputs: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build an implementation-independent request frame."""

    text = command_text.strip()
    lowered = text.casefold()
    change_markers = re.findall(
        r"\b(?:reusable|every future|after every|pipeline|workflow|extend|redesign|automate|"
        r"(?:create|build|design|compose|write|draft|produce|generate|prepare|assemble)\s+"
        r"(?:a\s+|an\s+|the\s+)?(?:new\s+)?(?:scientific\s+|technical\s+)?"
        r"(?:report|paper|manuscript|article|publication|dossier))\b",
        lowered,
    )
    one_off_override = bool(
        re.search(
            r"\b(?:one[- ]off|ad[ -]hoc|only for (?:this|the current)|not (?:a )?(?:reusable )?(?:workflow|pipeline))\b",
            lowered,
        )
    )
    negations = re.findall(
        r"\b(?:not|never|without|must not|do not|exclude)\b[^,.;]*", lowered
    )
    # Semicolons are common inside biomedical technical briefs and input
    # contracts; treating each one as a workflow boundary creates fictitious
    # decomposition. Split only on explicit sequencing language. The corpus'
    # artifact-handoff phrasing is also a genuine second intent even though it
    # begins a new sentence rather than using "and then".
    handoff = re.search(
        r"\buse the first artifact as evidence for a second, related task\b",
        text,
        flags=re.IGNORECASE,
    )
    if handoff and text[: handoff.start()].strip():
        clauses = [text[: handoff.start()].strip(), text[handoff.start() :].strip()]
    else:
        clauses = [
            part.strip()
            for part in re.split(
                r"\s+(?:and then|then|and also|plus)\s+", text, flags=re.IGNORECASE
            )
            if part.strip()
        ]
    frame = {
        "schema_version": FRAME_SCHEMA,
        "goal": text,
        "intent_units": [
            {"index": index, "text": clause} for index, clause in enumerate(clauses)
        ],
        "desired_artifacts": list(desired_outputs),
        "desired_inputs": list(desired_inputs),
        "supplied_inputs": dict(supplied_inputs or {}),
        "references": list(references),
        "constraints": negations,
        "excluded_terms": sorted(set(_tokens(negations))),
        "persistent_change_requested": bool(change_markers) and not one_off_override,
        "change_evidence": sorted(set(change_markers)),
        "desired_outcome": text,
        "consumer": str((supplied_inputs or {}).get("audience", "requesting user")),
        "supported_decision": str(
            (supplied_inputs or {}).get(
                "intended_use",
                (supplied_inputs or {}).get(
                    "supported_decision",
                    "inform the stated task without exceeding available evidence",
                ),
            )
        ),
        "artifact_type": list(desired_outputs) or ["planner-selected bounded artifact"],
        "evidence_scope": [
            "user request",
            *list(references),
            *[f"supplied_input:{key}" for key in sorted((supplied_inputs or {}))],
        ],
        "prohibited_inference": [
            *negations,
            "do not exceed the authority or claim ceiling of admitted evidence",
        ],
        "assumptions": [
            "the requesting user is the initial consumer unless another audience is stated"
        ],
        "success_level": "decision-supporting and evidence-bounded",
        "unresolved_material_intent": [],
    }
    explicit_consequence = (supplied_inputs or {}).get(
        "quality_consequence_profile",
        (supplied_inputs or {}).get("consequence_profile", {}),
    )
    frame["consequence_profile"] = normalize_consequence_profile(
        text,
        explicit_profile=(
            explicit_consequence if isinstance(explicit_consequence, Mapping) else {}
        ),
    )
    frame["digest"] = _digest(frame)
    return frame


def classify_quality_risk(frame: Mapping[str, Any]) -> str:
    """Return the consequence-based policy tier for compatibility callers."""

    return str(classify_quality_policy(frame)["tier"])


def _quality_principal(principal: Mapping[str, Any] | None) -> dict[str, Any]:
    """Quality principal."""
    return dict(principal or {"id": "bioagents-user", "kind": "user"})


def _criterion_for_requirement(
    requirement: Mapping[str, Any], *, version: int, frame: Mapping[str, Any]
) -> dict[str, Any]:
    """Criterion for requirement."""
    requirement_id = str(requirement["requirement_id"])
    statement = str(requirement.get("active_text", requirement.get("text", ""))).strip()
    prohibited = list(frame.get("prohibited_inference", ()))
    return {
        "schema_version": QUALITY_CRITERION_SCHEMA,
        "criterion_id": f"outcome-{requirement_id}",
        "lifecycle": "provisional",
        "created_in_version": version,
        "requirement_ids": [requirement_id],
        "consumer": str(frame.get("consumer", "requesting user")),
        "source": {
            "kind": "user",
            "pointer": f"requirement_ledger.requirements.{requirement_id}",
        },
        "observable": (
            f"Required outcome: {statement}. The artifact must preserve every "
            "requested entity, operation, distinction, and qualifier."
        ),
        "required_anchors": ["candidate artifact", f"requirement:{requirement_id}"],
        "allowed_evidence": list(frame.get("evidence_scope", ())),
        "evaluator_mode": "hybrid",
        "separation_required": True,
        "severity": "must_pass",
        "pass_condition": "Every material part of the quoted obligation is present and evidence-bounded, with no contradictory claim.",
        "failure_consequence": "revise",
        "allowed_variability": "Wording and organization may vary; meaning, qualifiers, and requested distinctions may not.",
        "prohibited_outcomes": prohibited
        or ["omit a material part of the obligation", "invent evidence"],
        "authority_ceiling": "decision support within the caller's declared authority",
        "examples": {
            "positive": f"The response addresses {statement!r} and visibly preserves its evidence boundary.",
            "negative": "A fluent response discusses the topic but omits one requested distinction or strengthens the claim.",
            "edge": "A concise response may pass only when every material clause remains observable and anchored.",
        },
        "invalidation_inputs": [
            "active requirement",
            "consumer",
            "evidence whitelist",
            "authority ceiling",
            "supported decision",
        ],
        "user_confirmable": True,
    }


def build_outcome_quality_contract(
    frame: Mapping[str, Any],
    requirement_ledger: Mapping[str, Any],
    *,
    principal: Mapping[str, Any] | None = None,
    version: int = 1,
) -> dict[str, Any]:
    """Create pre-route criterion seeds using no catalog or selected-component data."""

    requirements = [
        row
        for row in requirement_ledger.get("requirements", ())
        if row.get("status") == "active"
    ]
    criteria = [
        _criterion_for_requirement(row, version=version, frame=frame)
        for row in requirements
    ]
    interaction_id = str(
        frame.get("dialogue_id", frame.get("digest", "interaction"))
    ).replace("sha256:", "interaction-")
    evidence_manifest = _digest(sorted(frame.get("evidence_scope", ())))
    contract = {
        "schema_version": OUTCOME_QUALITY_SCHEMA,
        "contract_id": f"outcome-{interaction_id}-v{version}",
        "version": version,
        "lifecycle": "provisional",
        "root_interaction_id": interaction_id,
        "operation_role": "criterion_synthesis",
        "parent_digest": frame.get("digest"),
        "principal": _quality_principal(principal),
        "canonical_serialization": "canonical-json-v1",
        "evidence_manifest_digest": evidence_manifest,
        "requirement_ids": [str(row["requirement_id"]) for row in requirements],
        "criteria": criteria,
        "criterion_consumer_trace": {
            row["criterion_id"]: row["consumer"] for row in criteria
        },
        "evidence_whitelist": list(frame.get("evidence_scope", ())),
        "risk_tier": classify_quality_risk(frame),
        "review_status": "pending",
        "presentable_as_user_answer": False,
    }
    return seal_quality_contract(contract)


def review_quality_plan(
    plan: Mapping[str, Any],
    *,
    reviewer: Mapping[str, Any] | None = None,
    independent: bool = True,
) -> dict[str, Any]:
    """Lint criterion adequacy independently of any future candidate artifact."""

    report = validate_contract(plan)
    criteria = list(plan.get("criteria", ()))
    requirement_ids = set(map(str, plan.get("requirement_ids", ())))
    covered = {str(item) for row in criteria for item in row.get("requirement_ids", ())}
    generic = [
        row.get("criterion_id")
        for row in criteria
        if len(_tokens(row.get("observable", ""))) < 5
        or str(row.get("observable", "")).startswith(
            "The artifact must expose the concrete entities"
        )
    ]
    unavailable = [
        row.get("criterion_id") for row in criteria if not row.get("allowed_evidence")
    ]
    authority_failures = [
        row.get("criterion_id")
        for row in criteria
        if not row.get("authority_ceiling") or not row.get("prohibited_outcomes")
    ]
    checks = {
        "coverage": {
            "passed": not (requirement_ids - covered),
            "missing": sorted(requirement_ids - covered),
        },
        "specificity": {"passed": not generic, "failed_criteria": generic},
        "feasibility": {"passed": not unavailable, "failed_criteria": unavailable},
        "authority": {
            "passed": not authority_failures,
            "failed_criteria": authority_failures,
        },
        "conflicts": {"passed": True, "pairs": []},
        "architecture_bias": {
            "passed": plan.get("schema_version") != OUTCOME_QUALITY_SCHEMA
            or not plan.get("selected_target"),
            "evidence": "outcome contract has no selected-target field",
        },
    }
    failed = [name for name, check in checks.items() if not check["passed"]]
    verdict = (
        "pass"
        if not report.errors and not failed and independent
        else ("fail" if report.errors or failed else "inconclusive")
    )
    review = {
        "schema_version": QUALITY_REVIEW_SCHEMA,
        "review_id": f"review-{str(plan.get('digest', 'unknown'))[-16:]}",
        "root_interaction_id": plan["root_interaction_id"],
        "operation_role": "criterion_review",
        "parent_digest": plan["digest"],
        "principal": dict(plan["principal"]),
        "canonical_serialization": "canonical-json-v1",
        "evidence_manifest_digest": plan["evidence_manifest_digest"],
        "plan_digest": plan["digest"],
        "reviewer": dict(
            reviewer or {"id": "planner-quality-linter", "kind": "deterministic"}
        ),
        "independent": independent,
        "checks": checks,
        "verdict": verdict,
        "findings": [
            *report.errors,
            *[f"failed adequacy check: {name}" for name in failed],
        ],
        "presentable_as_user_answer": False,
    }
    return seal_quality_contract(review)


def quality_review_promotes_untrusted_candidate(
    reviewed_criterion: Mapping[str, Any],
    current_candidate: Mapping[str, Any],
    authorized_evidence: Mapping[str, Any],
) -> list[str]:
    """Return changed string leaves promoted by a positive criterion example.

    The artifact currently under review is a candidate, not evidence for newly
    asserted facts.  A semantic reviewer may describe its defect negatively,
    but it must not copy a changed candidate value into its positive example
    when the authorized evidence state disagrees.
    """

    changed: list[tuple[str, Any, Any]] = []

    def walk(candidate: Any, authorized: Any, pointer: str = "") -> None:
        """Walk."""
        if isinstance(candidate, Mapping) and isinstance(authorized, Mapping):
            for key in sorted(set(candidate) & set(authorized)):
                walk(candidate[key], authorized[key], f"{pointer}/{key}")
            return
        if candidate != authorized:
            changed.append((pointer, candidate, authorized))

    walk(current_candidate, authorized_evidence)
    positive = json.dumps(
        reviewed_criterion.get("positive_example"), ensure_ascii=False
    ).casefold()
    violations: list[str] = []
    for pointer, candidate, authorized in changed:
        if (
            not isinstance(candidate, str)
            or not candidate.strip()
            or candidate == authorized
        ):
            continue
        candidate_text = candidate.casefold()
        promoted_occurrence = False
        for match in re.finditer(
            rf"(?<!\w){re.escape(candidate_text)}(?!\w)", positive
        ):
            prefix_words = re.findall(
                r"[a-z0-9_-]+", positive[max(0, match.start() - 80) : match.start()]
            )[-6:]
            if not any(
                token
                in {
                    "no",
                    "not",
                    "never",
                    "neither",
                    "without",
                    "unavailable",
                    "blocked",
                }
                for token in prefix_words
            ):
                promoted_occurrence = True
                break
        if promoted_occurrence:
            violations.append(pointer)
    return violations


def freeze_quality_plan(
    plan: Mapping[str, Any], review: Mapping[str, Any]
) -> dict[str, Any]:
    """Freeze only the exact independently reviewed quality-plan bytes."""

    if (
        review.get("plan_digest") != plan.get("digest")
        or review.get("verdict") != "pass"
        or not review.get("independent")
    ):
        raise ValueError(
            "quality plan cannot freeze without a matching independent passed review"
        )
    frozen = dict(plan)
    frozen["lifecycle"] = "frozen"
    frozen["review_status"] = "passed"
    frozen["reviewed_plan_digest"] = review["plan_digest"]
    frozen["criteria"] = [
        {**row, "lifecycle": "frozen"} for row in plan.get("criteria", ())
    ]
    frozen = seal_quality_contract(frozen)
    if not validate_contract(frozen).valid:
        raise ValueError("frozen quality plan violates its contract")
    return frozen


def build_delivery_quality_plan(
    outcome_contract: Mapping[str, Any],
    selected: Mapping[str, Any] | None,
    binding: Mapping[str, Any],
    *,
    version: int = 1,
) -> dict[str, Any]:
    """Retain every outcome criterion and add route/binding integrity criteria."""

    if outcome_contract.get("lifecycle") not in {"provisional", "frozen"}:
        raise ValueError("delivery planning requires an active outcome contract")
    target_id = str((selected or {}).get("id", "unresolved-route"))
    criteria = [dict(row) for row in outcome_contract.get("criteria", ())]
    route_criterion = {
        "schema_version": QUALITY_CRITERION_SCHEMA,
        "criterion_id": "delivery-route-binding-integrity",
        "lifecycle": "provisional",
        "created_in_version": version,
        "requirement_ids": list(outcome_contract.get("requirement_ids", ())),
        "consumer": "authorized delivery adapter",
        "source": {
            "kind": "component_contract",
            "pointer": f"selected_target:{target_id}",
        },
        "observable": f"The delivery adapter invokes only the locked target {target_id!r}, binds every required port, and preserves outcome qualifiers through rendering.",
        "required_anchors": [
            "delivery handoff",
            "binding receipt",
            "rendered artifact digest",
        ],
        "allowed_evidence": [
            "selected target contract",
            "binding receipt",
            "candidate artifact",
        ],
        "evaluator_mode": "deterministic",
        "separation_required": False,
        "severity": "must_pass",
        "pass_condition": "Target identity, required bindings, plan digest, artifact digest, and rendered payload all match.",
        "failure_consequence": "block",
        "allowed_variability": "No identity, binding, qualifier, or digest variability is allowed.",
        "prohibited_outcomes": [
            "route substitution",
            "missing required binding",
            "post-assessment semantic rewrite",
        ],
        "authority_ceiling": "compile and assess only; the planner does not execute the selected component",
        "examples": {
            "positive": "All locked identities and digests match.",
            "negative": "A wrapper changes a caveat after assessment.",
            "edge": "Formatting-only changes require a new rendered digest.",
        },
        "invalidation_inputs": [
            "selected route",
            "component contract",
            "bindings",
            "rendered artifact",
        ],
        "user_confirmable": False,
    }
    criteria.append(route_criterion)
    plan = {
        "schema_version": DELIVERY_QUALITY_SCHEMA,
        "plan_id": f"delivery-{str(outcome_contract['contract_id'])}-v{version}",
        "version": version,
        "lifecycle": "provisional",
        "root_interaction_id": outcome_contract["root_interaction_id"],
        "operation_role": "criterion_synthesis",
        "parent_digest": outcome_contract["digest"],
        "principal": dict(outcome_contract["principal"]),
        "canonical_serialization": "canonical-json-v1",
        "evidence_manifest_digest": outcome_contract["evidence_manifest_digest"],
        "outcome_contract_digest": outcome_contract["digest"],
        "outcome_contract_lifecycle": outcome_contract["lifecycle"],
        "selected_target": dict(selected or {}),
        "requirement_ids": list(outcome_contract.get("requirement_ids", ())),
        "criteria": criteria,
        "criterion_consumer_trace": {
            row["criterion_id"]: row["consumer"] for row in criteria
        },
        "evidence_whitelist": [
            *outcome_contract.get("evidence_whitelist", ()),
            "selected target contract",
            "binding receipt",
            "candidate artifact",
        ],
        "evaluator_plan": {
            "deterministic_first": True,
            "independent_semantic_assessment": outcome_contract["risk_tier"]
            != "control",
            "human_gate": outcome_contract["risk_tier"] == "human_authority",
        },
        "release_policy": {
            "non_compensatory_must_pass": True,
            "unassessed_must_pass_blocks": True,
            "render_digest_continuity": True,
        },
        "risk_tier": outcome_contract["risk_tier"],
        "review_status": "pending",
        "presentable_as_user_answer": False,
    }
    return seal_quality_contract(plan)


def assess_quality_artifact(
    plan: Mapping[str, Any],
    artifact: Any,
    criterion_results: Iterable[Mapping[str, Any]],
    *,
    evaluator: Mapping[str, Any],
    producer_id: str | None = None,
) -> dict[str, Any]:
    """Bind per-criterion evidence to one exact artifact without judging it here."""

    if plan.get("lifecycle") != "frozen":
        raise ValueError("artifact assessment requires a frozen quality plan")
    artifact_digest = _digest(artifact)
    rows = [dict(row) for row in criterion_results]
    for row in rows:
        if row.get("artifact_digest") not in {None, artifact_digest}:
            raise ValueError(
                "criterion result does not bind the assessed artifact digest"
            )
        if row.get("quality_plan_digest") not in {None, plan.get("digest")}:
            raise ValueError(
                "criterion result does not bind the frozen quality plan digest"
            )
    expected = {str(row["criterion_id"]): row for row in plan.get("criteria", ())}
    observed = {str(row.get("criterion_id")): row for row in rows}
    missing = sorted(set(expected) - set(observed))
    independent = producer_id is None or str(evaluator.get("id")) != producer_id
    normalized: list[dict[str, Any]] = []
    for criterion_id, criterion in expected.items():
        result = observed.get(
            criterion_id,
            {
                "verdict": "inconclusive",
                "artifact_anchors": [],
                "source_anchors": [],
                "uncertainty": "missing result",
            },
        )
        verdict = str(result.get("verdict", "inconclusive"))
        if (
            criterion.get("severity") == "must_pass"
            and criterion.get("separation_required")
            and not independent
        ):
            verdict = "inconclusive"
        normalized.append(
            {
                "criterion_id": criterion_id,
                "severity": criterion["severity"],
                "evaluator_mode": criterion["evaluator_mode"],
                "verdict": verdict,
                "artifact_anchors": list(result.get("artifact_anchors", ())),
                "source_anchors": list(result.get("source_anchors", ())),
                "contradictions": list(result.get("contradictions", ())),
                "unsupported_claims": list(result.get("unsupported_claims", ())),
                "uncertainty": result.get("uncertainty"),
            }
        )
    fatal = [
        row
        for row in normalized
        if row["severity"] == "must_pass" and row["verdict"] == "fail"
    ]
    unresolved = [
        row
        for row in normalized
        if row["severity"] == "must_pass" and row["verdict"] != "pass"
    ]
    verdict = "fail" if fatal else ("inconclusive" if missing or unresolved else "pass")
    assessment = {
        "schema_version": QUALITY_ASSESSMENT_SCHEMA,
        "assessment_id": f"assessment-{artifact_digest[-16:]}",
        "root_interaction_id": plan["root_interaction_id"],
        "operation_role": "artifact_assessment",
        "parent_digest": plan["digest"],
        "principal": dict(plan["principal"]),
        "canonical_serialization": "canonical-json-v1",
        "evidence_manifest_digest": plan["evidence_manifest_digest"],
        "quality_plan_digest": plan["digest"],
        "artifact_digest": artifact_digest,
        "evaluator": dict(evaluator),
        "independent": independent,
        "criterion_results": normalized,
        "verdict": verdict,
        "presentable_as_user_answer": False,
    }
    return seal_quality_contract(assessment)


def decide_final_delivery(
    plan: Mapping[str, Any], assessment: Mapping[str, Any], artifact: Any
) -> dict[str, Any]:
    """Issue the mandatory non-compensatory release decision."""

    artifact_digest = _digest(artifact)
    reasons: list[str] = []
    plan_report = validate_contract(plan)
    assessment_report = validate_contract(assessment)
    if plan_report.errors:
        reasons.append("quality plan contract or digest is invalid")
    if assessment_report.errors:
        reasons.append("quality assessment contract or digest is invalid")
    if plan.get("lifecycle") != "frozen":
        reasons.append("quality plan is not frozen")
    if assessment.get("quality_plan_digest") != plan.get("digest"):
        reasons.append("assessment does not bind this quality plan")
    if assessment.get("artifact_digest") != artifact_digest:
        reasons.append("artifact changed after assessment")
    missing = set(str(row["criterion_id"]) for row in plan.get("criteria", ())) - {
        str(row.get("criterion_id")) for row in assessment.get("criterion_results", ())
    }
    if missing:
        reasons.append(f"must assess criteria: {sorted(missing)}")
    must_failures = [
        str(row.get("criterion_id"))
        for row in assessment.get("criterion_results", ())
        if row.get("severity") == "must_pass" and row.get("verdict") != "pass"
    ]
    if must_failures:
        reasons.append(f"must-pass criteria are unresolved: {must_failures}")
    if plan.get("risk_tier") == "human_authority" and not assessment.get(
        "human_review_complete"
    ):
        reasons.append("required human-authority review is incomplete")
    if assessment.get("verdict") == "fail":
        decision = "revise"
    elif reasons or assessment.get("verdict") == "inconclusive":
        decision = "inconclusive"
    else:
        decision = "release"
    value = {
        "schema_version": FINAL_DECISION_SCHEMA,
        "decision_id": f"decision-{artifact_digest[-16:]}",
        "root_interaction_id": plan["root_interaction_id"],
        "operation_role": "final_delivery",
        "parent_digest": assessment["digest"],
        "principal": dict(plan["principal"]),
        "canonical_serialization": "canonical-json-v1",
        "evidence_manifest_digest": plan["evidence_manifest_digest"],
        "quality_plan_digest": plan["digest"],
        "assessment_digest": assessment["digest"],
        "artifact_digest": artifact_digest,
        "decision": decision,
        "reasons": reasons,
        "next_action": (
            "present the assessed artifact"
            if decision == "release"
            else "repair the earliest failed criterion or obtain required review/input"
        ),
        "presentable_as_user_answer": decision == "release",
    }
    return seal_quality_contract(value)


def invalidate_quality_plan(
    plan: Mapping[str, Any], changed_inputs: Iterable[str], *, next_version: int
) -> dict[str, Any]:
    """Selectively supersede criteria whose declared dependencies changed."""

    changed = set(map(str, changed_inputs))
    revised = dict(plan)
    revised["version"] = next_version
    revised["lifecycle"] = "provisional"
    revised["review_status"] = "pending"
    revised["criteria"] = [
        {
            **row,
            "lifecycle": (
                "superseded"
                if changed & set(map(str, row.get("invalidation_inputs", ())))
                else row.get("lifecycle", "frozen")
            ),
        }
        for row in plan.get("criteria", ())
    ]
    revised["invalidated_by"] = sorted(changed)
    # The current v1 schemas deliberately reject this migration receipt as a
    # frozen plan; callers must resynthesize superseded criteria before review.
    return seal_quality_contract(revised)


def build_quality_repair(
    assessment: Mapping[str, Any], *, prior_attempts: int = 0, max_attempts: int = 2
) -> dict[str, Any]:
    """Propose one bounded repair for the earliest failed must-pass criterion."""

    failures = [
        row
        for row in assessment.get("criterion_results", ())
        if row.get("severity") == "must_pass"
        and row.get("verdict") in {"fail", "inconclusive"}
    ]
    primary = failures[0] if failures else None
    exhausted = prior_attempts >= max_attempts
    return {
        "schema_version": "lunar.planner.quality-repair/v1",
        "status": (
            "blocked_attempts_exhausted"
            if exhausted and primary
            else ("repair_required" if primary else "not_required")
        ),
        "attempt": min(
            prior_attempts + (1 if primary and not exhausted else 0), max_attempts
        ),
        "max_attempts": max_attempts,
        "primary_criterion_id": (primary or {}).get("criterion_id"),
        "earliest_responsible_surface": (
            ((primary or {}).get("artifact_anchors") or ["candidate artifact"])[0]
            if primary
            else None
        ),
        "rival_hypotheses": list((primary or {}).get("contradictions", ())),
        "minimal_fix": (
            f"change only the earliest surface needed to satisfy {(primary or {}).get('criterion_id')}"
            if primary and not exhausted
            else None
        ),
        "preserve_criterion_ids": [
            row.get("criterion_id")
            for row in assessment.get("criterion_results", ())
            if row.get("verdict") == "pass"
        ],
        "invalidate_criterion_ids": (
            [(primary or {}).get("criterion_id")] if primary else []
        ),
        "broad_rebuild_allowed": False,
        "automatic_repair_authorized": bool(
            primary
            and not exhausted
            and (primary or {}).get("evaluator_mode") != "human"
        ),
    }


def plan_control_request(
    command_text: str,
    *,
    mode: str,
    status: str,
    references: Iterable[str] = (),
    desired_inputs: Iterable[str] = (),
    desired_outputs: Iterable[str] = (),
    supplied_inputs: Mapping[str, Any] | None = None,
    blockers: Iterable[str] = (),
) -> dict[str, Any]:
    """Frame a control/denial request without semantic catalog retrieval."""

    frame = normalize_request(
        command_text,
        references=references,
        desired_inputs=desired_inputs,
        desired_outputs=desired_outputs,
        supplied_inputs=supplied_inputs,
    )
    frame.update(
        current_utterance=command_text.strip(),
        dialogue_id=f"dialogue-{frame['digest'][7:23]}",
        turn_index=1,
        request_class=mode,
        control_route=True,
    )
    frame["digest"] = _digest(
        {key: value for key, value in frame.items() if key != "digest"}
    )
    requirement = {
        "requirement_id": "req-control-1",
        "status": "active",
        "text": command_text.strip(),
        "active_text": command_text.strip(),
        "source_turn_index": 1,
    }
    ledger = {
        "schema_version": REQUIREMENT_LEDGER_SCHEMA,
        "requirements": [requirement],
    }
    ledger["digest"] = _digest(ledger)
    outcome = build_outcome_quality_contract(frame, ledger)
    # Control traffic has no biomedical semantic payload.  Its criterion is an
    # exact deterministic invariant, so it does not need (and must not fake) a
    # generative semantic adequacy judgment.
    outcome["criteria"] = [
        {
            **dict(outcome["criteria"][0]),
            "observable": (
                f"The control response reports mode {mode!r} and status {status!r}, "
                "performs no semantic catalog retrieval, and performs no execution."
            ),
            "required_anchors": ["control mode", "control status", "performed actions"],
            "evaluator_mode": "deterministic",
            "separation_required": False,
            "pass_condition": (
                "Mode and status equal the deterministic router result, no retrieval "
                "field is present, and the performed-action list is empty."
            ),
        }
    ]
    outcome["criterion_consumer_trace"] = {
        outcome["criteria"][0]["criterion_id"]: outcome["criteria"][0]["consumer"]
    }
    outcome = seal_quality_contract(outcome)
    outcome_review = review_quality_plan(
        outcome,
        reviewer={"id": "bioagents-deterministic-control-validator"},
        independent=True,
    )
    outcome = freeze_quality_plan(outcome, outcome_review)
    selected = {"id": f"control:{mode}", "kind": "control_route"}
    binding = {"status": "complete", "ports": [], "material_missing": []}
    delivery = build_delivery_quality_plan(outcome, selected, binding)
    delivery_review = review_quality_plan(
        delivery,
        reviewer={"id": "bioagents-deterministic-control-validator"},
        independent=True,
    )
    delivery = freeze_quality_plan(delivery, delivery_review)
    quality_policy = classify_quality_policy(frame)
    quality_handoff = {
        "schema_version": "lunar.planner.contextual-quality-handoff/v1",
        "outcome_contract_digest": outcome["digest"],
        "delivery_plan_digest": delivery["digest"],
        "must_pass_criterion_ids": [
            row["criterion_id"]
            for row in delivery["criteria"]
            if row["severity"] == "must_pass"
        ],
        "evidence_whitelist": delivery["evidence_whitelist"],
        "risk_tier": delivery["risk_tier"],
        "assessment_required": False,
        "independent_quality_validation_required": bool(
            quality_policy["independent_semantic_review"]
        ),
        "release_authorized": status != "denied",
        "route_only": True,
        "release_semantics": "deterministic_control_receipt_only",
        "semantic_payload_release_authorized": False,
    }
    quality_handoff["digest"] = _digest(quality_handoff)
    receipt = {
        "schema_version": RECEIPT_SCHEMA,
        "request_frame": frame,
        "decomposition": [
            {
                "unit": {
                    "index": 0,
                    "text": command_text.strip(),
                    "requirement_id": "req-control-1",
                },
                "disposition": mode,
                "selected": selected,
                "serious_alternatives": [],
            }
        ],
        "requirement_ledger": ledger,
        "adjudication": {
            "status": "control_route",
            "selected": selected,
            "rejected": [],
        },
        "binding": binding,
        "preflight": {
            "fit_status": "control",
            "availability_status": "available",
            "authority_status": "denied" if status == "denied" else "allowed",
        },
        "disposition": status,
        "primary_failure_owner": "authority" if status == "denied" else None,
        "outcome_quality_contract": outcome,
        "outcome_quality_review": outcome_review,
        "delivery_quality_plan": delivery,
        "delivery_quality_review": delivery_review,
        "quality_handoff": quality_handoff,
        "quality_disposition": (
            "deterministic_control_released"
            if status != "denied"
            else "deterministic_control_denied"
        ),
        "control_route": True,
        "route_only": True,
        "blockers": list(blockers),
        "deterministic_control_checks": {
            "mode_bound": True,
            "status_bound": True,
            "semantic_catalog_retrieval_performed": False,
            "execution_performed": False,
            "passed": status != "denied",
        },
    }
    receipt["digest"] = _digest(receipt)
    return receipt


def _component_rows(surface: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Project only public catalog-agent skills into planner retrieval.

    The generated surface also carries planner-internal descriptors for exact
    control routes. Those are not end-user scientific capabilities and remain
    outside this searchable component view.
    """
    rows: list[dict[str, Any]] = []
    for row in surface.get("skills", ()):
        if row.get("scope") not in {"planner", "project_support"}:
            rows.append({**row, "id": row.get("id", row.get("name")), "kind": "skill"})
    rows.extend(
        dict(row)
        for row in surface.get("workflow_packages", ())
        if row.get("available")
    )
    rows.extend(
        dict(row) for row in surface.get("subworkflows", ()) if row.get("available")
    )
    return rows


def _retrieval_snapshot(
    surface: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, list[str]]], Counter[str]]:
    """Tokenize one sealed component surface once per planner process."""

    rows = _component_rows(surface)
    docs = {
        str(row.get("id", row.get("name"))): {
            lane: _features(_document(row, lane))
            for lane in ("identity", "purpose", "input", "output", "boundary")
        }
        for row in rows
    }
    frequencies: Counter[str] = Counter(
        token
        for lanes in docs.values()
        for token in set(chain.from_iterable(lanes.values()))
    )
    value = (rows, docs, frequencies)
    return value


def _semantic_retrieval_adjustment(frame, component_id):
    """Apply only a selected-package adjustment to an already-admitted candidate."""
    result: Any = policy_value(
        "candidate_adjustment",
        {"frame": frame, "component_id": component_id},
        {"score": 0, "reasons": []},
    )
    score = float(result.get("score", 0))
    if not math.isfinite(score):
        raise ValueError("non-finite package candidate adjustment")
    return score, list(result.get("reasons", ()))


def _bounded_reader_product_request(frame):
    """Allow the selected package to classify a bounded input product."""
    return bool(policy_value("bounded_input_product", {"frame": frame}, False))


def gather_candidates(
    frame: Mapping[str, Any],
    surface: Mapping[str, Any],
    limit: int = 12,
    *,
    exact_route_hint: str | None = None,
) -> dict[str, Any]:
    """Retrieve one bounded, cross-kind shortlist with lane-level evidence."""

    rows, docs, frequencies = _retrieval_snapshot(surface)
    excluded = set(frame.get("excluded_terms", ()))
    query = [
        feature
        for feature in _features(
            [frame["goal"], frame.get("desired_artifacts"), frame.get("desired_inputs")]
        )
        if not (set(feature.split("::")) & excluded)
    ]
    supplied_names = {str(name) for name in frame.get("supplied_inputs", {})}
    scored: list[dict[str, Any]] = []
    for row in rows:
        identity = str(row.get("id", row.get("name")))
        lane_scores: dict[str, float] = {}
        for lane, tokens in docs[identity].items():
            overlap = set(query) & set(tokens)
            # Identity is a semantic lane (including tokenized role/outcome
            # words), not exact-name routing. Weight it above long narrative
            # and output lists so broad contracts cannot win merely by
            # accumulating many generic query terms.
            weight = {
                "identity": 6.0,
                "purpose": 1.4,
                "input": 1.2,
                "output": 1.7,
                "boundary": -0.8,
            }[lane]
            lane_scores[lane] = round(
                sum(
                    math.log((len(rows) + 1) / (frequencies[t] + 1)) + 1
                    for t in overlap
                )
                * weight,
                6,
            )
        contract_ports = {
            str(port["name"])
            for port in _required_ports(row)
            if isinstance(port.get("name"), str)
        }
        matched_input_ports = sorted(supplied_names & contract_ports)
        if matched_input_ports:
            lane_scores["input"] = round(
                lane_scores["input"] + 30.0 * len(matched_input_ports), 6
            )
        positive = sum(
            value for lane, value in lane_scores.items() if lane != "boundary"
        )
        semantic_adjustment, semantic_reasons = _semantic_retrieval_adjustment(
            frame, identity
        )
        score = positive + lane_scores["boundary"] + semantic_adjustment
        # A semantic-role adjustment is itself explicit planner evidence.  It
        # may admit a verifier whose concise contract does not repeat the
        # report's surface vocabulary (for example, "cached/staged/live").
        if positive > 0 or semantic_adjustment > 0:
            scored.append(
                {
                    "id": identity,
                    "kind": row.get("kind", "skill"),
                    "source_path": row.get("source_path"),
                    "content_digest": row.get("content_digest"),
                    "available": bool(row.get("available")),
                    "invocation_posture": row.get(
                        "invocation_posture", row.get("execution_posture")
                    ),
                    "score": round(score, 6),
                    "retrieval_lanes": lane_scores,
                    "matched_terms": sorted(
                        set(query) & set(chain.from_iterable(docs[identity].values()))
                    ),
                    "matched_input_ports": matched_input_ports,
                    "semantic_score_adjustment": semantic_adjustment,
                    "semantic_routing_reasons": semantic_reasons,
                    "contract": row,
                }
            )
    scored.sort(key=lambda item: (-item["score"], item["id"]))
    if exact_route_hint:
        # A governed exact/domain route was resolved before the quality pause.
        # It must remain inside the sealed shortlist after the outcome freeze;
        # otherwise the bounded lexical limit can silently discard the route
        # before adjudication has a chance to preserve it.
        pinned = next((item for item in scored if item["id"] == exact_route_hint), None)
        if pinned is None:
            row = next(
                (
                    item
                    for item in chain(rows, surface.get("skills", ()))
                    if str(item.get("id", item.get("name"))) == exact_route_hint
                    or str(item.get("name", "")) == exact_route_hint
                    or (
                        item.get("scope") not in {"planner", "project_support"}
                        and f"{item.get('scope', 'package')}:{item.get('name', '')}"
                        == exact_route_hint
                    )
                ),
                None,
            )
            if row is not None:
                pinned = {
                    "id": exact_route_hint,
                    "kind": row.get("kind", "skill"),
                    "source_path": row.get("source_path"),
                    "content_digest": row.get("content_digest"),
                    "available": bool(row.get("available")),
                    "invocation_posture": row.get(
                        "invocation_posture", row.get("execution_posture")
                    ),
                    "score": 0.0,
                    "retrieval_lanes": {},
                    "matched_terms": [],
                    "matched_input_ports": [],
                    "semantic_score_adjustment": 0.0,
                    "semantic_routing_reasons": [
                        "governed exact route retained across the outcome-quality freeze"
                    ],
                    "contract": row,
                }
                scored.append(pinned)
        if pinned is not None:
            scored = [pinned, *(item for item in scored if item is not pinned)]
    return {
        "query_terms": sorted(set(query)),
        "limit": limit,
        "candidates": scored[:limit],
    }


def _required_ports(contract: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Required ports."""
    if contract.get("kind") == "planning_subworkflow" or "inputs" in contract:
        return [
            dict(port)
            for port in contract.get("inputs", ())
            if port.get("required", True)
        ]
    interface = contract.get("interface", {}).get("inputs", {})
    if interface.get("status") != "documented":
        return []
    return [
        (
            dict(port)
            if isinstance(port, Mapping)
            else {"name": str(port), "required": True}
        )
        for port in interface.get("items", ())
        if not isinstance(port, Mapping) or port.get("required", True)
    ]


def adjudicate(
    frame: Mapping[str, Any],
    retrieval: Mapping[str, Any],
    *,
    exact_route_hint: str | None = None,
) -> dict[str, Any]:
    """Choose semantic fit from only the sealed shortlist."""

    candidates = list(retrieval.get("candidates", ()))
    if not candidates:
        return {
            "status": "no_local_match",
            "selected": None,
            "rejected": [],
            "reason": "no candidate has positive contract evidence",
        }
    # The legacy entrypoint has already resolved an explicit component name or
    # governed alias against the same sealed surface.  Preserve that exact
    # identity after the outcome freeze; semantic sibling scores must not turn
    # ``run serial_ctdna`` into an ambiguity with ``serial_ctdna_causal``.
    if exact_route_hint:
        exact = next(
            (row for row in candidates if str(row.get("id")) == str(exact_route_hint)),
            None,
        )
        if exact is not None:
            selected = {
                key: exact.get(key)
                for key in (
                    "id",
                    "kind",
                    "source_path",
                    "content_digest",
                    "available",
                    "invocation_posture",
                )
            }
            return {
                "status": "selected",
                "selected": selected,
                "rejected": [
                    {
                        "id": row["id"],
                        "reason": "explicit exact-name route has precedence",
                    }
                    for row in candidates
                    if row["id"] != exact["id"]
                ],
                "covered_obligations": list(exact.get("matched_terms", ())),
                "uncovered_obligations": [],
                "granularity_reason": "planner-owned exact-name identity preserved after outcome freeze",
            }
    available = [row for row in candidates if row.get("available", True)]
    top_feature_count = len(candidates[0].get("matched_terms", ()))
    viable_available = [
        row
        for row in available
        if row["score"] >= candidates[0]["score"] * 0.65
        and len(row.get("matched_terms", ()))
        >= max(1, math.ceil(top_feature_count * 0.75))
    ]
    if not candidates[0].get("available", True) and viable_available:
        candidates = viable_available

    # A minimum evidence floor prevents ordinary verbs from manufacturing a
    # local biomedical fit. A close serious sibling produces clarification.
    def is_substantive(feature: str) -> bool:
        """Is substantive."""
        return any(part not in _TASK_TERMS for part in feature.split("::"))

    # Among candidates with comparable weighted scores, prefer the contract
    # covering more independent words/phrases from the expert's obligation.
    # This closes an abstraction gap where a narrow identity token (for
    # example, "annotation") otherwise beats a contract matching the full
    # operation (tumour alterations, expression, and clinical annotations).
    strongest_port_fit = max(
        (len(row.get("matched_input_ports", ())) for row in candidates), default=0
    )
    pool = (
        [
            row
            for row in candidates
            if len(row.get("matched_input_ports", ())) == strongest_port_fit
        ]
        if strongest_port_fit
        else candidates
    )
    competitive = [row for row in pool if row["score"] >= pool[0]["score"] * 0.85]
    competitive.sort(
        key=lambda row: (
            -int(bool(row.get("semantic_routing_reasons"))),
            -float(row.get("semantic_score_adjustment", 0)),
            -len(
                {term for term in row.get("matched_terms", ()) if is_substantive(term)}
            ),
            -row["score"],
            row["id"],
        )
    )
    first = competitive[0]
    remaining = [row for row in candidates if row["id"] != first["id"]]
    serious_remaining = [row for row in pool if row["id"] != first["id"]]
    second = serious_remaining[0] if serious_remaining else None

    substantive = {term for term in first["matched_terms"] if is_substantive(term)}
    request_substantive = {
        term for term in retrieval.get("query_terms", ()) if is_substantive(term)
    }
    if not request_substantive:
        return {
            "status": "clarification_required",
            "selected": None,
            "serious_alternatives": [item["id"] for item in candidates[:2]],
            "rejected": [c["id"] for c in candidates[2:]],
            "reason": "request lacks a material outcome, input, or domain distinction",
        }
    semantic_role_evidence = bool(
        first.get("semantic_score_adjustment", 0) > 0
        and first.get("semantic_routing_reasons")
    )
    if first["score"] < 2.0 or (not substantive and not semantic_role_evidence):
        return {
            "status": "no_local_match",
            "selected": None,
            "rejected": [c["id"] for c in candidates],
            "reason": "contract evidence below the semantic-fit floor",
        }
    identity_separated = bool(
        second
        and first.get("retrieval_lanes", {}).get("identity", 0)
        >= max(1.0, second.get("retrieval_lanes", {}).get("identity", 0) * 1.25)
    )
    feature_separated = bool(
        second
        and len(
            {term for term in first.get("matched_terms", ()) if is_substantive(term)}
        )
        >= max(
            2,
            math.ceil(
                len(
                    {
                        term
                        for term in second.get("matched_terms", ())
                        if is_substantive(term)
                    }
                )
                * 1.25
            ),
        )
    )
    if (
        second
        and second["score"] >= first["score"] * 0.94
        and second["kind"] == first["kind"]
        and not (identity_separated or feature_separated)
    ):
        return {
            "status": "clarification_required",
            "selected": None,
            "serious_alternatives": [first["id"], second["id"]],
            "rejected": [c["id"] for c in candidates[2:]],
            "reason": "two candidates have materially indistinguishable contract fit",
        }
    selected = {
        key: first.get(key)
        for key in (
            "id",
            "kind",
            "source_path",
            "content_digest",
            "available",
            "invocation_posture",
        )
    }
    rejected = [
        {"id": item["id"], "reason": "lower output/input/purpose compatibility"}
        for item in remaining
    ]
    return {
        "status": "selected",
        "selected": selected,
        "rejected": rejected,
        "covered_obligations": first["matched_terms"],
        "uncovered_obligations": [],
        "granularity_reason": "highest bounded contract fit with no equally fitting same-kind sibling",
    }


def bind_inputs(
    frame: Mapping[str, Any], contract: Mapping[str, Any] | None
) -> dict[str, Any]:
    """Bind supplied values to declared ports while retaining missing inputs."""

    supplied = dict(frame.get("supplied_inputs", {}))
    ports = _required_ports(contract or {})
    bindings: list[dict[str, Any]] = []
    used: set[str] = set()
    for port in ports:
        name = str(port["name"])
        if name in supplied:
            value = supplied[name]
            if isinstance(value, Mapping) and value.get("_conflict"):
                status = "conflicting"
            elif value is None:
                status = "invalid"
            else:
                status = "bound"
            bindings.append(
                {
                    "port": name,
                    "type": port.get("type", "unknown"),
                    "status": status,
                    "value": value,
                    "source": f"request.supplied_inputs.{name}",
                }
            )
            used.add(name)
        else:
            bindings.append(
                {
                    "port": name,
                    "type": port.get("type", "unknown"),
                    "status": "missing",
                    "value": None,
                    "source": None,
                }
            )
    bindings.extend(
        {
            "port": name,
            "type": "unknown",
            "status": "unused",
            "value": value,
            "source": f"request.supplied_inputs.{name}",
        }
        for name, value in supplied.items()
        if name not in used
    )
    if (
        not ports
        and not _bounded_reader_product_request(frame)
        and re.search(
            r"\b(?:material|evidence|inputs?|facts?|records?)\b[^.]{0,240}\b(?:incomplete|missing|unavailable|conflicting)\b",
            str(frame.get("goal", "")),
            flags=re.IGNORECASE,
        )
    ):
        bindings.append(
            {
                "port": "material_source_or_decision_fields",
                "type": "outcome-relevant evidence",
                "status": "missing",
                "value": None,
                "source": "request.explicit_incompleteness",
            }
        )
    missing = [
        item["port"]
        for item in bindings
        if item["status"] in {"missing", "conflicting", "invalid"}
    ]
    return {
        "status": "needs_input" if missing else "complete",
        "ports": bindings,
        "material_missing": missing,
    }


def preflight(
    selected: Mapping[str, Any] | None,
    contract: Mapping[str, Any] | None,
    authority: Mapping[str, Any],
) -> dict[str, Any]:
    """Check selected-component fit, availability, posture, and authority."""

    if not selected:
        return {
            "fit_status": "not_selected",
            "availability_status": "not_checked",
            "authority_status": "not_checked",
            "posture": None,
            "claim_ceiling": None,
        }
    permissions = set((contract or {}).get("authority", {}).get("permissions", ()))
    denied_envelope = set(authority.get("denied_permissions", ()))
    contract_text = " ".join(
        _tokens(
            [
                (selected or {}).get("id"),
                (contract or {}).get("description"),
                (contract or {}).get("purpose"),
                (contract or {}).get("triggers"),
            ]
        )
    )
    inferred_network_operation = bool(
        re.search(
            r"\b(?:api|mcp)\s+(?:call|client|server|service|query)\b|"
            r"\bconnector\s+(?:call|execution|query|retrieval)\b|"
            r"\b(?:external|remote|network)\s+(?:api|call|service|query|retrieval)\b|"
            r"\b(?:query|retrieve|search|fetch)\b[^.;]{0,35}\b(?:database|portal|api|service)\b",
            contract_text,
        )
    )
    if "network" in denied_envelope and inferred_network_operation:
        permissions.add("network")
    denied = permissions & denied_envelope
    available = bool(selected.get("available", True))
    posture = (
        selected.get("invocation_posture")
        or (contract or {}).get("execution_posture")
        or "instruction_only"
    )
    return {
        "fit_status": "fit",
        "availability_status": "available" if available else "unavailable",
        "authority_status": "denied" if denied else "allowed",
        "denied_permissions": sorted(denied),
        "posture": posture,
        "claim_ceiling": (contract or {})
        .get("authority", {})
        .get("claim_ceiling", "contract_declared_only"),
    }


_OUTCOME_VERBS = {
    "analyze",
    "analyse",
    "assess",
    "assemble",
    "audit",
    "build",
    "check",
    "compare",
    "create",
    "critic",
    "critique",
    "decide",
    "design",
    "detect",
    "evaluate",
    "explain",
    "expose",
    "find",
    "harmonize",
    "identify",
    "include",
    "ingest",
    "integrate",
    "interpret",
    "consolidate",
    "link",
    "map",
    "model",
    "normalize",
    "organize",
    "organise",
    "plan",
    "prioritize",
    "prioritise",
    "produce",
    "query",
    "rank",
    "report",
    "retain",
    "revise",
    "search",
    "stage",
    "summarize",
    "test",
    "trace",
    "validate",
    "verify",
    "write",
}
_CORRECTION_MARKERS = re.compile(
    r"(?:^\s*(?:actually|correction\s*:|I meant|to clarify)\b)|(?:\bnot\s+[^,.;]{1,80}\s+but\b)",
    flags=re.IGNORECASE,
)


def _state_digest(value: Mapping[str, Any]) -> str:
    """State digest."""
    payload = {key: item for key, item in value.items() if key != "digest"}
    return _digest(payload)


def _active_rows(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Active rows."""
    return [dict(row) for row in rows if row.get("status", "active") == "active"]


def _negated_term_sets(text: str) -> list[set[str]]:
    """Negated term sets."""
    spans = re.findall(
        r"\bnot\s+([^,.;]+)|\brather than\s+([^,.;]+)|\binstead of\s+([^,.;]+)",
        text,
        flags=re.IGNORECASE,
    )
    return [
        set(_tokens(next(part for part in match if part)))
        for match in spans
        if any(match)
    ]


def _turn_is_requirement(text: str, turn_index: int) -> bool:
    """Turn is requirement."""
    if turn_index == 1:
        return True
    if re.search(
        r"\b(?:produce|finalize|finalise|freeze|return|deliver|give me)\b[^.]{0,100}\b(?:the|this|our)\s+(?:[a-z0-9-]+\s+){0,3}workflow\b",
        text,
        flags=re.IGNORECASE,
    ):
        return False
    terms = set(_tokens(text))
    return bool(terms & _OUTCOME_VERBS) or bool(
        re.search(
            r"\b(?:I|we)\s+(?:also\s+)?(?:need|want|would like|have to)\b",
            text,
            flags=re.IGNORECASE,
        )
    )


def _requirement_rows_for_turn(
    text: str,
    turn_id: str,
    start_index: int,
    *,
    context_text: str | None = None,
) -> list[dict[str, Any]]:
    """Requirement rows for turn."""
    stage_list = re.search(
        r"\b(?:finalize|finalise|produce|return)\s+(?:the\s+)?(?:final\s+|reusable\s+)*(.+?)\s+stages?\b",
        text,
        flags=re.IGNORECASE,
    )
    if stage_list:
        labels = [
            re.sub(r"^and\s+", "", item.strip(), flags=re.IGNORECASE)
            for item in re.split(r"\s*,\s*|\s+and\s+", stage_list.group(1))
            if item.strip()
        ]
        if (
            "checking" in {label.casefold() for label in labels}
            and "formalization" not in {label.casefold() for label in labels}
            and re.search(
                r"\b(?:claim|premise|proof|source statement|formal)\b",
                context_text or "",
                flags=re.IGNORECASE,
            )
        ):
            labels.insert(
                labels.index(
                    next(label for label in labels if label.casefold() == "checking")
                ),
                "formalization",
            )
        trailing_constraints = text[stage_list.end() :].strip().rstrip(".")
        context_prefix = (
            f"Within the workflow outcome '{context_text}', " if context_text else ""
        )
        units = [
            {
                "index": index,
                "text": f"{context_prefix}provide the requested {label} stage {trailing_constraints}".strip(),
            }
            for index, label in enumerate(labels)
        ]
        frame = {"intent_units": units}
    else:
        frame = normalize_request(text)
    rows: list[dict[str, Any]] = []
    for offset, unit in enumerate(frame["intent_units"]):
        requirement_text = str(unit["text"])
        rows.append(
            {
                "requirement_id": f"requirement-{start_index + offset}",
                "status": "active",
                "text": requirement_text,
                "active_text": requirement_text,
                "source_turn_ids": [turn_id],
                "qualification_turn_ids": [],
                "desired_output": "a bounded artifact or decision satisfying the stated requested outcome",
                "correctness_criteria": [
                    f"output demonstrably satisfies the source obligation: {requirement_text}",
                    "use only supplied or source-backed facts",
                    "preserve uncertainty, provenance, and authority boundaries",
                ],
                "stability": (
                    "stable"
                    if re.search(
                        r"\b(?:workflow|pipeline|reusable|build|design|create)\b",
                        requirement_text,
                        flags=re.IGNORECASE,
                    )
                    else "provisional"
                ),
            }
        )
    return rows


def _correction_target(
    requirements: Iterable[MutableMapping[str, Any]], text: str
) -> MutableMapping[str, Any] | None:
    """Resolve a correction to the closest active obligation, with recency as tie-breaker."""

    candidates = [row for row in requirements if row.get("status") == "active"]
    if not candidates:
        return None
    terms = set(_tokens(text)) - _TASK_TERMS
    return max(
        candidates,
        key=lambda row: (
            len(
                terms
                & (
                    set(_tokens(row.get("active_text", row.get("text", ""))))
                    - _TASK_TERMS
                )
            ),
            int(str(row.get("requirement_id", "requirement-0")).rsplit("-", 1)[-1]),
        ),
    )


def _independent_action_clauses(text: str) -> list[str]:
    """Extract explicit additional outcomes from a correction or qualification.

    Punctuation alone is not treated as workflow structure. A later clause must
    start with an operational verb, which preserves constraints while allowing
    experts to correct one obligation and introduce another in the same turn.
    """

    clauses = [part.strip() for part in re.split(r"[.;]\s+", text) if part.strip()]
    actions: list[str] = []
    for clause in clauses[1:]:
        if not re.match(
            r"^(?:also\s+)?(?:audit|compare|consolidate|critique|design|map|normalize|plan|produce|query|rank|revise|screen|stage|trace|verify)\b",
            clause,
            flags=re.IGNORECASE,
        ):
            continue
        actions.append(f"{clauses[0]}; {clause}")
    return actions


def reduce_dialogue_state(
    command_text: str,
    *,
    snapshot_digest: str,
    supplied_inputs: Mapping[str, Any] | None = None,
    references: Iterable[str] = (),
    authority_envelope: Mapping[str, Any] | None = None,
    prior_state: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Reduce one user turn into caller-held, evidence-addressed dialogue state.

    This reducer deliberately records revisions instead of flattening the
    transcript. It does not infer biomedical facts from conversational prose;
    typed values are accepted only from ``supplied_inputs``.
    """

    prior = dict(prior_state or {})
    prior_turns = [dict(row) for row in prior.get("turns", ())]
    prior_facts = [dict(row) for row in prior.get("facts", ())]
    requirements = [
        dict(row) for row in prior.get("requirement_ledger", {}).get("requirements", ())
    ]
    turn_index = int(prior.get("turn_index", 0)) + 1
    turn_id = f"turn-{turn_index}"
    correction = bool(_CORRECTION_MARKERS.search(command_text))
    negated_sets = _negated_term_sets(command_text)
    withdrawal = re.search(
        r"\b(?:no longer need|drop|remove|withdraw)\s+([^,.;]+)",
        command_text,
        flags=re.IGNORECASE,
    )

    superseded_turn_ids: list[str] = []
    if correction and negated_sets:
        for row in prior_turns:
            if row.get("status", "active") != "active":
                continue
            terms = set(_tokens(row.get("utterance", "")))
            if any(
                negated and len(terms & negated) / len(negated) >= 0.6
                for negated in negated_sets
            ):
                row["status"] = "superseded"
                row["superseded_by"] = turn_id
                superseded_turn_ids.append(str(row["turn_id"]))

    prior_turns.append(
        {
            "turn_id": turn_id,
            "turn_index": turn_index,
            "utterance": command_text.strip(),
            "status": "active",
            "relation": (
                "correct" if correction else ("state" if turn_index == 1 else "qualify")
            ),
            "supersedes_turn_ids": superseded_turn_ids,
        }
    )

    fact_events: list[dict[str, Any]] = []
    for name, value in dict(supplied_inputs or {}).items():
        active = next(
            (
                row
                for row in reversed(prior_facts)
                if row.get("name") == name and row.get("status") == "active"
            ),
            None,
        )
        relation = "add"
        if active is not None:
            if isinstance(value, Mapping) and value.get("_retract") is True:
                relation = "retract"
            elif isinstance(value, Mapping) and value.get("_conflict"):
                relation = "contradict"
            elif active.get("value") == value:
                relation = "confirm"
            else:
                relation = "replace"
            if relation in {"replace", "retract", "contradict"}:
                active["status"] = (
                    "superseded"
                    if relation in {"replace", "contradict"}
                    else "withdrawn"
                )
                active["superseded_by"] = f"fact-{name}-{turn_index}"
        if relation != "retract":
            fact = {
                "fact_id": f"fact-{name}-{turn_index}",
                "name": name,
                "value": value,
                "status": "active",
                "relation": relation,
                "source_turn_id": turn_id,
                "source": f"turns.{turn_id}.supplied_inputs.{name}",
            }
            prior_facts.append(fact)
            fact_events.append(fact)
        else:
            fact_events.append(
                {"name": name, "relation": relation, "source_turn_id": turn_id}
            )

    non_answer = bool(
        re.search(
            r"\b(?:do not know|don't know|not available|unavailable|still (?:being )?(?:assembled|decided|collected)|cannot answer|unsure)\b",
            command_text,
            flags=re.IGNORECASE,
        )
    )
    finalization_turn = bool(requirements) and bool(
        re.match(
            r"^\s*(?:finalize|finalise|freeze)\b", command_text, flags=re.IGNORECASE
        )
        or (
            re.match(
                r"^\s*(?:produce|return|deliver|give me)\b",
                command_text,
                flags=re.IGNORECASE,
            )
            and re.search(
                r"\b(?:final|instantiated|workflow|pipeline)\b",
                command_text,
                flags=re.IGNORECASE,
            )
        )
    )
    if not non_answer and not finalization_turn:
        for question in prior.get("question_history", ()):
            intent = str(question.get("intent", ""))
            if question.get("status") != "open" or not intent.startswith("supply:"):
                continue
            name = intent.split(":", 1)[1]
            if name in dict(supplied_inputs or {}) or any(
                row.get("name") == name and row.get("status") == "active"
                for row in prior_facts
            ):
                continue
            if not (set(_tokens(name.replace("_", " "))) & set(_tokens(command_text))):
                continue
            fact = {
                "fact_id": f"fact-{name}-{turn_index}",
                "name": name,
                "value": {"text": command_text.strip()},
                "status": "active",
                "relation": "add",
                "source_turn_id": turn_id,
                "source": f"turns.{turn_id}.utterance",
            }
            prior_facts.append(fact)
            fact_events.append(fact)

    if withdrawal and requirements:
        withdrawn_terms = set(_tokens(withdrawal.group(1)))
        candidates = [row for row in requirements if row.get("status") == "active"]
        target = max(
            candidates,
            key=lambda row: len(
                withdrawn_terms
                & set(_tokens(row.get("active_text", row.get("text", ""))))
            ),
            default=None,
        )
        if target is not None:
            target["status"] = "withdrawn"
            target["withdrawn_turn_id"] = turn_id
            target["withdrawal_evidence"] = withdrawal.group(0)
    elif correction and requirements:
        target = _correction_target(requirements, command_text)
        if target:
            additions = _independent_action_clauses(command_text)
            if additions:
                next_index = 1 + max(
                    (
                        int(
                            str(row.get("requirement_id", "requirement-0")).rsplit(
                                "-", 1
                            )[-1]
                        )
                        for row in requirements
                    ),
                    default=0,
                )
                for addition in additions:
                    requirements.extend(
                        _requirement_rows_for_turn(
                            addition,
                            turn_id,
                            next_index,
                            context_text=str(
                                requirements[0].get(
                                    "active_text", requirements[0].get("text", "")
                                )
                            ),
                        )
                    )
                    next_index = 1 + max(
                        int(str(row["requirement_id"]).rsplit("-", 1)[-1])
                        for row in requirements
                    )
            else:
                target.setdefault("qualification_turn_ids", []).append(turn_id)
                target.setdefault("source_turn_ids", []).append(turn_id)
                replaces_scope = bool(
                    re.search(r"\bone[- ]off\b", command_text, flags=re.IGNORECASE)
                    and re.search(
                        r"\b(?:reusable|workflow|pipeline)\b",
                        command_text,
                        flags=re.IGNORECASE,
                    )
                )
                target["active_text"] = (
                    command_text.strip()
                    if replaces_scope
                    else f"{target.get('text', '')}; {command_text.strip()}"
                )
                target["correctness_criteria"] = [
                    f"output demonstrably satisfies the source obligation: {target['active_text']}",
                    "use only supplied or source-backed facts",
                    "preserve uncertainty, provenance, and authority boundaries",
                ]
                target["revision"] = (
                    "replaced_scope" if replaces_scope else "corrected_or_qualified"
                )
                target["stability"] = (
                    "stable"
                    if re.search(
                        r"\b(?:workflow|pipeline|reusable|build|design|create)\b",
                        target["active_text"],
                        flags=re.IGNORECASE,
                    )
                    else target.get("stability", "provisional")
                )
    elif finalization_turn:
        next_index = 1 + max(
            (
                int(str(row.get("requirement_id", "requirement-0")).rsplit("-", 1)[-1])
                for row in requirements
            ),
            default=0,
        )
        if re.search(r"\bstages?\b", command_text, flags=re.IGNORECASE):
            stage_rows = _requirement_rows_for_turn(
                command_text,
                turn_id,
                next_index,
                context_text=(
                    str(
                        requirements[0].get(
                            "active_text", requirements[0].get("text", "")
                        )
                    )
                    if requirements
                    else None
                ),
            )
            requirements.extend(stage_rows)
            next_index += len(stage_rows)
        delivery = {
            "requirement_id": f"requirement-{next_index}",
            "status": "active",
            "text": command_text.strip(),
            "active_text": command_text.strip(),
            "source_turn_ids": [turn_id],
            "qualification_turn_ids": [],
            "desired_output": (
                state_output
                if (
                    state_output := dict(supplied_inputs or {}).get("terminal_artifact")
                )
                else next(
                    (
                        row.get("value")
                        for row in reversed(prior_facts)
                        if row.get("name") == "terminal_artifact"
                        and row.get("status") == "active"
                    ),
                    command_text.strip(),
                )
            ),
            "correctness_criteria": [
                f"terminal delivery demonstrably satisfies: {command_text.strip()}",
                "all blockers, unresolved assumptions, and missing execution evidence remain explicit",
                "prohibited claims and authority boundaries are preserved",
            ],
            "stability": "stable",
            "requirement_kind": "delivery_contract",
        }
        requirements.append(delivery)
    elif _turn_is_requirement(
        command_text, turn_index
    ) and "workflow_execution_results" not in dict(supplied_inputs or {}):
        next_index = 1 + max(
            (
                int(str(row.get("requirement_id", "requirement-0")).rsplit("-", 1)[-1])
                for row in requirements
            ),
            default=0,
        )
        requirements.extend(
            _requirement_rows_for_turn(
                command_text,
                turn_id,
                next_index,
                context_text=(
                    str(
                        requirements[0].get(
                            "active_text", requirements[0].get("text", "")
                        )
                    )
                    if requirements
                    else None
                ),
            )
        )
    elif requirements and not finalization_turn:
        target = next(row for row in requirements if row.get("status") == "active")
        target.setdefault("qualification_turn_ids", []).append(turn_id)
        target["active_text"] = (
            f"{target.get('active_text', target.get('text', ''))}; {command_text.strip()}"
        )

    active_inputs = {
        str(row["name"]): row["value"]
        for row in prior_facts
        if row.get("status") == "active"
    }
    active_turns = _active_rows(prior_turns)
    active_goal = " Then ".join(str(row["utterance"]) for row in active_turns)
    all_references = list(
        dict.fromkeys(
            [*prior.get("references", ()), *(str(item) for item in references)]
        )
    )
    merged_authority = {
        **dict(prior.get("authority", {})),
        **dict(authority_envelope or {}),
    }
    current_constraints = normalize_request(command_text).get("constraints", ())
    constraints = list(
        dict.fromkeys([*prior.get("constraints", ()), *current_constraints])
    )
    ledger = {
        "schema_version": REQUIREMENT_LEDGER_SCHEMA,
        "requirements": requirements,
    }
    ledger["digest"] = _state_digest(ledger)
    state = {
        "schema_version": DIALOGUE_STATE_SCHEMA,
        # Dialogue identity is request-derived. Catalog changes must not alter
        # the pre-route outcome contract for an otherwise identical request.
        "dialogue_id": prior.get("dialogue_id")
        or f"dialogue-{_digest(command_text)[7:23]}",
        "turn_index": turn_index,
        "parent_stage_digest": prior.get("current_stage_digest"),
        "current_stage_digest": None,
        "snapshot_digest": snapshot_digest,
        "turns": prior_turns,
        "active_goal": active_goal,
        "facts": prior_facts,
        "fact_events": fact_events,
        "active_inputs": active_inputs,
        "references": all_references,
        "authority": merged_authority,
        "constraints": constraints,
        "assumptions": list(prior.get("assumptions", ())),
        "open_decisions": list(prior.get("open_decisions", ())),
        "requirement_ledger": ledger,
        "workflow_draft": dict(prior.get("workflow_draft", {})),
        "workflow_instantiation": prior.get("workflow_instantiation"),
        "proposed_skill_test_plans": list(prior.get("proposed_skill_test_plans", ())),
        "workflow_refinement_cycle": prior.get("workflow_refinement_cycle"),
        "capability_gap_plan": prior.get("capability_gap_plan"),
        "question_history": [dict(row) for row in prior.get("question_history", ())],
        "planning_phase": "framing" if turn_index == 1 else "draft_workflow",
    }
    state["digest"] = _state_digest(state)
    return state


def _gap_class(requirement: str) -> tuple[str, list[str]]:
    """Classify an unresolved obligation without claiming a component exists."""

    lowered = requirement.casefold()
    markers = {
        "adapter": (
            "api",
            "connector",
            "external",
            "import",
            "export",
            "format",
            "portal",
            "service",
            "sparql",
            "graphql",
        ),
        "project_specific": (
            "catalog",
            "ci",
            "repository",
            "release",
            "project convention",
            "project-level",
            "test harness",
        ),
        "universal": (
            "across workflows",
            "different contexts",
            "independent",
            "reusable",
            "general-purpose",
            "universal",
        ),
    }
    for component_class in ("adapter", "project_specific", "universal"):
        hits = sorted(
            {marker for marker in markers[component_class] if marker in lowered}
        )
        if hits:
            return component_class, hits
    return "workflow_local", [
        "no evidence of a stable cross-workflow, project-governance, or external-system boundary"
    ]


def _resolve_requirement_candidate(
    requirement_text: str,
    frame: Mapping[str, Any],
    surface: Mapping[str, Any],
    *,
    exact_route_hint: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any], float]:
    """Apply one semantic-fit policy to drafting and capability-gap planning."""

    unit_frame = {**frame, "goal": requirement_text}
    stage_match = re.search(
        r"\brequested\s+([a-z-]+)\s+stage\b", requirement_text, flags=re.IGNORECASE
    )
    retrieval = gather_candidates(
        unit_frame,
        surface,
        limit=200 if stage_match else 12,
        exact_route_hint=exact_route_hint,
    )
    # Theme placement does not determine dispatchability. Scientific intake,
    # explanation, and lifecycle components under ``orchestration/`` remain
    # valid workflow nodes; only the planner entrypoint itself is absent from
    # the admitted scientific-skill surface.
    candidates = list(retrieval["candidates"])
    if stage_match:
        role_terms = {
            "intake": {"intake", "interpreter"},
            "checking": {"runner", "checker", "auditor", "verifier", "gate"},
            "formalization": {"autoformalization", "autoformalizer"},
            "critique": {"critic", "auditor", "reviewer"},
            "explanation": {"explainer", "rewriter", "writer", "reporter"},
        }.get(stage_match.group(1).casefold(), set())
        role_candidates = [
            row
            for row in candidates
            if role_terms
            & set(re.findall(r"[a-z]+", str(row.get("id", "")).casefold()))
            and not (
                stage_match.group(1).casefold() == "formalization"
                and "critic" in str(row.get("id", "")).casefold()
            )
        ]
        if role_candidates:
            candidates = sorted(
                role_candidates,
                key=lambda row: (
                    -len(row.get("matched_terms", ())),
                    -row["score"],
                    row["id"],
                ),
            )
    retrieval = {
        **retrieval,
        "candidates": candidates,
        "excluded_governance_candidates": [],
    }
    decision = adjudicate(unit_frame, retrieval, exact_route_hint=exact_route_hint)
    selected_row = next(
        (
            row
            for row in candidates
            if row["id"] == (decision.get("selected") or {}).get("id")
        ),
        candidates[0] if candidates else None,
    )
    substantive_query = (
        set(_tokens(requirement_text))
        - _TASK_TERMS
        - {
            "workflow",
            "reusable",
            "pipeline",
            "stage",
        }
    )
    matched_substantive = (
        set(selected_row.get("matched_terms", ())) - _TASK_TERMS
        if selected_row
        else set()
    )
    coverage = len(matched_substantive & substantive_query) / max(
        1, len(substantive_query)
    )
    # Long expert requests contain domain context, constraints, and outputs that
    # no concise skill description should repeat. Require either meaningful
    # fractional coverage or two independent operational/domain features.
    semantic_role_evidence = bool(
        selected_row
        and selected_row.get("semantic_score_adjustment", 0) > 0
        and selected_row.get("semantic_routing_reasons")
    )
    sufficient = (
        bool(
            exact_route_hint
            and (decision.get("selected") or {}).get("id") == exact_route_hint
        )
        or coverage >= 0.25
        or len(matched_substantive & substantive_query) >= 2
        or semantic_role_evidence
    )
    if decision["status"] in {"selected", "clarification_required"} and not sufficient:
        decision = {
            "status": "no_local_match",
            "selected": None,
            "rejected": [row["id"] for row in candidates],
            "reason": "candidate lacks sufficient operational or domain evidence for the obligation",
        }
    return retrieval, decision, coverage


def _composition_outcome(
    requirement_text: str,
    requirement_index: int,
    requirement_count: int,
    retrieval: Mapping[str, Any],
    decision: Mapping[str, Any],
) -> bool:
    """Recognize an umbrella workflow outcome discharged by later responsibilities."""

    if (
        requirement_index != 0
        or requirement_count < 2
        or not re.search(
            r"\b(?:workflow|pipeline)\b", requirement_text, flags=re.IGNORECASE
        )
    ):
        return False
    selected_id = (decision.get("selected") or {}).get("id")
    selected_row = next(
        (
            row
            for row in retrieval.get("candidates", ())
            if row.get("id") == selected_id
        ),
        None,
    )
    if not selected_row:
        return True
    if re.search(r"(?:^|-)(?:coordinator|router)(?:-|$)", str(selected_id)):
        return True
    matched = {
        term
        for term in selected_row.get("matched_terms", ())
        if any(
            part not in (_TASK_TERMS | {"workflow", "pipeline"})
            for part in term.split("::")
        )
    }
    alternatives = [
        row for row in retrieval.get("candidates", ()) if row.get("id") != selected_id
    ]
    next_score = float(alternatives[0]["score"]) if alternatives else 0.0
    purpose_dominant = len(matched) >= 5 and float(selected_row.get("score", 0)) >= max(
        2.0, next_score * 1.25
    )
    identity_specific = (
        float(selected_row.get("retrieval_lanes", {}).get("identity", 0)) > 0
        and len(matched) >= 3
    )
    return not (purpose_dominant or identity_specific)


def plan_capability_gaps(
    frame: Mapping[str, Any],
    surface: Mapping[str, Any],
    *,
    requirement_rows: Iterable[Mapping[str, Any]] | None = None,
    prior_plan: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Exhaust reuse per intent unit, then type only genuinely unresolved work.

    Gap rows are design evidence. They deliberately carry unavailable status
    and cannot be dispatched or treated as catalog identities.
    """

    requirements: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    reused: list[dict[str, Any]] = []
    retracted: list[dict[str, Any]] = []
    prior_gaps = {
        str(row.get("requirement_id")): dict(row)
        for row in (prior_plan or {}).get("gaps", ())
    }
    source_requirements = list(requirement_rows or ())
    if not source_requirements:
        source_requirements = [
            {
                "requirement_id": f"requirement-{unit['index'] + 1}",
                "text": unit["text"],
                "active_text": unit["text"],
                "stability": "stable",
                "desired_output": "a bounded result satisfying the obligation",
                "correctness_criteria": [
                    "satisfy the stated obligation without inventing inputs"
                ],
            }
            for unit in frame.get("intent_units", ())
        ]
    for index, source in enumerate(source_requirements):
        requirement_text = str(source.get("active_text", source.get("text", "")))
        retrieval, decision, coverage = _resolve_requirement_candidate(
            requirement_text, frame, surface
        )
        delivery_contract = source.get("requirement_kind") == "delivery_contract"
        composition_outcome = _composition_outcome(
            requirement_text, index, len(source_requirements), retrieval, decision
        )
        evidence = {
            "surface_digest": _digest(surface),
            "candidate_ids": [row["id"] for row in retrieval["candidates"]],
            "candidate_count": len(retrieval["candidates"]),
            "adjudication": decision["status"],
            "excluded_governance_candidates": retrieval.get(
                "excluded_governance_candidates", []
            ),
            "obligation_coverage": round(coverage, 6),
        }
        requirement = {
            "requirement_id": str(
                source.get("requirement_id", f"requirement-{index + 1}")
            ),
            "text": requirement_text,
            "desired_output": source.get(
                "desired_output", "a bounded result satisfying the obligation"
            ),
            "correctness_criteria": list(source.get("correctness_criteria", ())),
            "stability": source.get("stability", "stable"),
            "reuse_evidence": evidence,
        }
        if delivery_contract:
            requirement.update(status="delivery_contract")
        elif composition_outcome:
            requirement.update(
                status="covered_by_composition",
                composed_requirement_ids=[
                    str(row.get("requirement_id"))
                    for row in source_requirements[index + 1 :]
                    if row.get("status", "active") == "active"
                ],
            )
        elif decision["status"] == "selected":
            requirement.update(status="covered_by_reuse", selected=decision["selected"])
            reused.append(
                {
                    "requirement_id": requirement["requirement_id"],
                    "component": decision["selected"],
                }
            )
            if requirement["requirement_id"] in prior_gaps:
                retracted.append(
                    {
                        **prior_gaps[requirement["requirement_id"]],
                        "status": "retracted",
                        "retraction_reason": "later dialogue state established sufficient existing reuse",
                        "replacement_component": decision["selected"],
                    }
                )
        elif (
            decision["status"] == "clarification_required"
            and requirement["stability"] != "stable"
        ):
            requirement.update(
                status="needs_qualification",
                alternatives=decision.get("serious_alternatives", []),
            )
        elif requirement["stability"] != "stable":
            requirement.update(
                status="deferred", reason="requirement boundary is still provisional"
            )
        else:
            component_class, basis = _gap_class(requirement_text)
            gap = {
                "gap_id": f"gap-{requirement['requirement_id'].removeprefix('requirement-')}",
                "requirement_id": requirement["requirement_id"],
                "obligation": requirement_text,
                "proposed_component_class": component_class,
                "classification_basis": basis,
                "proposed_interface": {
                    "inputs": list(frame.get("desired_inputs", ()))
                    or ["source-backed inputs required by the obligation"],
                    "output": requirement["desired_output"],
                    "correctness_criteria": requirement["correctness_criteria"],
                    "invariants": [
                        "do not invent missing inputs",
                        "preserve source provenance, uncertainty, and authority boundaries",
                    ],
                    "failure_states": [
                        "missing_input",
                        "conflicting_input",
                        "insufficient_evidence",
                        "unavailable_dependency",
                    ],
                    "claim_ceiling": "no stronger than supplied and source-backed evidence",
                    "transfer_expectation": "class must be reviewed against independent contexts before universal promotion",
                },
                "availability": "proposed_unavailable",
                "catalog_identity": None,
                "creation_authorized": False,
                "reuse_exhausted": True,
                "reuse_evidence": evidence,
                "next_review": "review stable boundary and monotonic reuse before authoring",
            }
            requirement.update(status="capability_gap", gap_id=gap["gap_id"])
            gaps.append(gap)
        requirements.append(requirement)
    status = (
        "gaps_identified"
        if gaps
        else (
            "needs_qualification"
            if any(
                row["status"] in {"needs_qualification", "deferred"}
                for row in requirements
            )
            else "reuse_complete"
        )
    )
    plan = {
        "schema_version": "lunar.planner.capability-gap-plan/v1",
        "status": status,
        "requirements": requirements,
        "reused_components": reused,
        "gaps": gaps,
        "retracted_gaps": retracted,
        "classification_vocabulary": sorted(GAP_CLASSES),
        "reuse_first": True,
        "authoring_performed": False,
    }
    plan["digest"] = _digest(plan)
    return plan


def _contract_output_type(contract: Mapping[str, Any]) -> str | None:
    """Contract output type."""
    outputs = contract.get("outputs") or contract.get("interface", {}).get(
        "outputs", {}
    ).get("items", ())
    if isinstance(outputs, Mapping):
        outputs = outputs.get("items", ())
    for item in outputs or ():
        if isinstance(item, Mapping):
            return str(item.get("type") or item.get("name") or "") or None
        if item:
            return str(item)
    terminals = contract.get("terminals", ())
    if terminals:
        first = terminals[0]
        return (
            str(first.get("type") or first.get("name"))
            if isinstance(first, Mapping)
            else str(first)
        )
    return None


def build_workflow_draft(
    state: Mapping[str, Any],
    frame: Mapping[str, Any],
    surface: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Resolve active requirements independently into an auditable typed DAG."""

    requirements: list[dict[str, Any]] = []
    nodes: list[dict[str, Any]] = []
    contracts_by_node: dict[str, Mapping[str, Any]] = {}
    source_rows = list(state.get("requirement_ledger", {}).get("requirements", ()))
    prior_nodes = {
        str(row.get("requirement_id")): dict(row)
        for row in state.get("workflow_draft", {}).get("nodes", ())
        if row.get("requirement_id")
    }
    active_count = sum(row.get("status") == "active" for row in source_rows)
    active_index = 0
    for source in source_rows:
        requirement = dict(source)
        if requirement.get("status") != "active":
            requirements.append(requirement)
            continue
        requirement_text = str(
            requirement.get("active_text", requirement.get("text", ""))
        )
        consumes_prior_artifact = bool(
            active_index > 0
            and re.search(
                r"\buse the first artifact as evidence for a second, related task\b",
                requirement_text,
                flags=re.IGNORECASE,
            )
        )
        current_turn_id = f"turn-{state.get('turn_index')}"
        requirement_changed_this_turn = current_turn_id in set(
            map(str, requirement.get("source_turn_ids", ()))
        ) or current_turn_id in set(
            map(str, requirement.get("qualification_turn_ids", ()))
        )
        requirement_frame = normalize_request(
            requirement_text,
            references=frame.get("references", ()),
            desired_inputs=frame.get("desired_inputs", ()),
            desired_outputs=frame.get("desired_artifacts", ()),
            supplied_inputs=(
                {}
                if consumes_prior_artifact or not requirement_changed_this_turn
                else frame.get("supplied_inputs", {})
            ),
        )
        retrieval, decision, obligation_coverage = _resolve_requirement_candidate(
            str(requirement.get("active_text", requirement.get("text", ""))),
            requirement_frame,
            surface,
            exact_route_hint=(
                (str(state.get("exact_route_hint") or "") or None)
                if active_count == 1 and not frame.get("persistent_change_requested")
                else None
            ),
        )
        prior_node = prior_nodes.get(str(requirement.get("requirement_id")))
        prior_selected_id = str((prior_node or {}).get("component", {}).get("id", ""))
        prior_candidate = next(
            (
                row
                for row in retrieval.get("candidates", ())
                if row.get("id") == prior_selected_id and row.get("available", True)
            ),
            None,
        )
        if prior_candidate and not requirement_changed_this_turn:
            decision = {
                "status": "selected",
                "selected": {
                    key: prior_candidate.get(key)
                    for key in (
                        "id",
                        "kind",
                        "source_path",
                        "content_digest",
                        "available",
                        "invocation_posture",
                    )
                },
                "serious_alternatives": [],
                "reason": "unchanged active requirement retains its still-admissible prior component while bindings are re-evaluated",
            }
        if requirement.get("requirement_kind") == "delivery_contract":
            decision = {
                "status": "delivery_contract",
                "selected": None,
                "serious_alternatives": [],
                "reason": "terminal delivery is a workflow contract, not a reusable scientific component",
            }
        elif _composition_outcome(
            str(requirement.get("active_text", requirement.get("text", ""))),
            active_index,
            active_count,
            retrieval,
            decision,
        ):
            decision = {
                "status": "covered_by_composition",
                "selected": None,
                "serious_alternatives": [],
                "reason": "umbrella workflow outcome is discharged by its explicit child responsibilities",
            }
        active_index += 1
        selected = decision.get("selected")
        candidate = next(
            (
                row
                for row in retrieval["candidates"]
                if row["id"] == (selected or {}).get("id")
            ),
            None,
        )
        contract = dict(candidate.get("contract", {})) if candidate else {}
        binding_frame = {
            **requirement_frame,
            "supplied_inputs": (
                {} if consumes_prior_artifact else frame.get("supplied_inputs", {})
            ),
        }
        binding = (
            bind_inputs(binding_frame, contract)
            if selected
            else {"status": "not_started", "ports": [], "material_missing": []}
        )
        check = preflight(selected, contract, state.get("authority", {}))
        requirement["planner_decision"] = {
            "disposition": decision["status"],
            "selected": selected,
            "serious_alternatives": list(decision.get("serious_alternatives", ())),
            "binding_status": binding["status"],
            "preflight": check,
            "obligation_coverage": round(obligation_coverage, 6),
        }
        requirements.append(requirement)
        if selected:
            node_id = f"node-{len(nodes) + 1}"
            node = {
                "node_id": node_id,
                "requirement_id": requirement["requirement_id"],
                "component": selected,
                "bindings": binding["ports"],
                "preflight": check,
                "output_type": _contract_output_type(contract)
                or "contract_declared_artifact",
            }
            nodes.append(node)
            contracts_by_node[node_id] = contract

    formal_ids = " ".join(
        str((node.get("component") or {}).get("id", "")) for node in nodes
    )
    if re.search(
        r"\b(?:autoformalization|bioreason|causal-request|causal-assumption|lean-kernel|open-obligation|checked-claim)\b",
        formal_ids,
    ):

        def formal_rank(node: Mapping[str, Any]) -> int:
            """Formal rank."""
            identifier = str((node.get("component") or {}).get("id", ""))
            if node.get("implementation_kind") == "workflow_composition":
                return 0
            if "causal-request" in identifier or "causal-assumption" in identifier:
                return 10
            if any(
                term in identifier
                for term in (
                    "autoformalization-job",
                    "autoformalizer",
                    "premise-selector",
                    "obligation-emitter",
                )
            ):
                return 20
            if "critic" in identifier or "auditor" in identifier:
                return 30
            if "kernel" in identifier or "checker" in identifier:
                return 40
            if "obligation-reporter" in identifier:
                return 50
            if "explainer" in identifier or "rewriter" in identifier:
                return 60
            return 35

        nodes = [
            row
            for _index, row in sorted(
                enumerate(nodes), key=lambda item: (formal_rank(item[1]), item[0])
            )
        ]

    operational_nodes = [
        node
        for node in nodes
        if node.get("implementation_kind") != "workflow_composition"
    ]
    edges: list[dict[str, Any]] = []
    for left, right in pairwise(operational_nodes):
        right_contract = contracts_by_node.get(right["node_id"], {})
        right_inputs = {
            str(port.get("type", "unknown")) for port in _required_ports(right_contract)
        }
        output_type = str(left["output_type"])
        compatible = (
            output_type in right_inputs
            if right_inputs and output_type != "contract_declared_artifact"
            else False
        )
        edges.append(
            {
                "edge_id": f"edge-{len(edges) + 1}",
                "from_node": left["node_id"],
                "to_node": right["node_id"],
                "artifact_type": output_type,
                "required_input_types": sorted(right_inputs),
                "compatibility": (
                    "documented_compatible" if compatible else "requires_mapping_review"
                ),
                "invented_mapping": False,
            }
        )

    gates: list[dict[str, Any]] = []
    for node in nodes:
        if any(row["status"] != "bound" for row in node["bindings"]):
            gates.append(
                {
                    "gate": "input_binding",
                    "node_id": node["node_id"],
                    "status": "blocked",
                }
            )
        if node["preflight"]["authority_status"] != "allowed":
            gates.append(
                {"gate": "authority", "node_id": node["node_id"], "status": "blocked"}
            )
    terminal = state.get("active_inputs", {}).get("terminal_artifact") or (
        nodes[-1]["output_type"] if nodes else None
    )
    draft = {
        "schema_version": WORKFLOW_DRAFT_SCHEMA,
        "dialogue_id": state["dialogue_id"],
        "turn_index": state["turn_index"],
        "status": "draft" if nodes else "needs_framing",
        "nodes": nodes,
        "edges": edges,
        "gates": gates,
        "critics": ["contract_and_claim_boundary_review"] if nodes else [],
        "terminal_artifact": terminal,
        "unresolved_requirement_ids": [
            row["requirement_id"]
            for row in requirements
            if row.get("status") == "active"
            and row.get("planner_decision", {}).get("disposition") != "selected"
        ],
        "route_only": True,
    }
    draft["digest"] = _state_digest(draft)
    ledger = {"schema_version": REQUIREMENT_LEDGER_SCHEMA, "requirements": requirements}
    ledger["digest"] = _state_digest(ledger)
    return ledger, draft


def instantiate_workflow(
    state: Mapping[str, Any],
    requirement_ledger: Mapping[str, Any],
    workflow_draft: Mapping[str, Any],
    capability_gap_plan: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Instantiate every active requirement as reuse, a governed gap, or a blocker.

    Proposed nodes and their tests are concrete planning artifacts, not newly
    authored or executable catalog components.
    """

    draft_by_requirement = {
        str(node["requirement_id"]): dict(node)
        for node in workflow_draft.get("nodes", ())
    }
    gap_by_requirement = {
        str(gap["requirement_id"]): dict(gap)
        for gap in (capability_gap_plan or {}).get("gaps", ())
    }
    composition_by_requirement = {
        str(row["requirement_id"]): dict(row)
        for row in (capability_gap_plan or {}).get("requirements", ())
        if row.get("status") == "covered_by_composition"
    }
    delivery_by_requirement = {
        str(row["requirement_id"]): dict(row)
        for row in (capability_gap_plan or {}).get("requirements", ())
        if row.get("status") == "delivery_contract"
    }
    active_requirements = [
        dict(row)
        for row in requirement_ledger.get("requirements", ())
        if row.get("status") == "active"
    ]
    nodes: list[dict[str, Any]] = []
    skill_tests: list[dict[str, Any]] = []
    for requirement in active_requirements:
        requirement_id = str(requirement["requirement_id"])
        existing = draft_by_requirement.get(requirement_id)
        gap = gap_by_requirement.get(requirement_id)
        composition = composition_by_requirement.get(requirement_id)
        delivery = delivery_by_requirement.get(requirement_id)
        if delivery:
            node = {
                "node_id": f"instantiated-{len(nodes) + 1}",
                "requirement_id": requirement_id,
                "implementation_kind": "workflow_delivery_contract",
                "component": None,
                "status": "ready",
                "inputs": [],
                "output_type": requirement.get("desired_output")
                or requirement.get("active_text"),
                "correctness_criteria": list(
                    requirement.get("correctness_criteria", ())
                ),
                "creation_authorized": False,
            }
        elif composition:
            node = {
                "node_id": f"instantiated-{len(nodes) + 1}",
                "requirement_id": requirement_id,
                "implementation_kind": "workflow_composition",
                "component": None,
                "status": "ready",
                "inputs": [],
                "output_type": "composed_workflow_plan",
                "correctness_criteria": list(
                    requirement.get("correctness_criteria", ())
                ),
                "composed_requirement_ids": composition.get(
                    "composed_requirement_ids", []
                ),
                "creation_authorized": False,
            }
        elif existing:
            blocked = (
                any(
                    row.get("status") in {"missing", "conflicting", "invalid"}
                    for row in existing.get("bindings", ())
                )
                or existing.get("preflight", {}).get("authority_status") != "allowed"
                or existing.get("preflight", {}).get("availability_status")
                != "available"
            )
            node = {
                "node_id": f"instantiated-{len(nodes) + 1}",
                "requirement_id": requirement_id,
                "implementation_kind": "existing_component",
                "component": existing["component"],
                "status": "blocked" if blocked else "ready",
                "inputs": [
                    row
                    for row in existing.get("bindings", [])
                    if row.get("status") != "unused"
                ],
                "output_type": existing.get("output_type"),
                "correctness_criteria": list(
                    requirement.get("correctness_criteria", ())
                ),
                "preflight": existing.get("preflight", {}),
                "creation_authorized": False,
            }
        elif gap:
            test_plan_id = f"test-plan-{gap['gap_id']}"
            interface = dict(gap.get("proposed_interface", {}))
            test_cases = [
                {
                    "test_id": f"{gap['gap_id']}-contract",
                    "purpose": "validate the proposed input and output contract",
                    "arrange": interface.get("inputs", []),
                    "act": "invoke the future component through its reviewed adapter",
                    "assert": [
                        interface.get("output"),
                        *interface.get("correctness_criteria", []),
                    ],
                },
                {
                    "test_id": f"{gap['gap_id']}-missing-input",
                    "purpose": "fail closed when a required input is absent",
                    "arrange": ["omit one required input"],
                    "act": "run contract preflight",
                    "assert": [
                        "typed missing_input result",
                        "no fabricated value",
                        "no external mutation",
                    ],
                },
                {
                    "test_id": f"{gap['gap_id']}-conflict",
                    "purpose": "preserve conflicting evidence",
                    "arrange": [
                        "supply two incompatible values for one material field"
                    ],
                    "act": "run contract preflight",
                    "assert": [
                        "typed conflicting_input result",
                        "conflict remains visible",
                    ],
                },
                {
                    "test_id": f"{gap['gap_id']}-claim-boundary",
                    "purpose": "enforce provenance and the proposed claim ceiling",
                    "arrange": ["supply evidence insufficient for a definitive claim"],
                    "act": "request the proposed output",
                    "assert": [
                        interface.get("claim_ceiling"),
                        "source provenance is retained",
                    ],
                },
            ]
            if gap.get("proposed_component_class") == "universal":
                test_cases.append(
                    {
                        "test_id": f"{gap['gap_id']}-transfer",
                        "purpose": "test independent reuse outside the originating workflow",
                        "arrange": [
                            "two reviewed contexts with the same semantic contract"
                        ],
                        "act": "bind each context independently",
                        "assert": [
                            "both outputs satisfy the same correctness criteria",
                            "no project-local assumption leaks",
                        ],
                    }
                )
            if gap.get("proposed_component_class") == "adapter":
                test_cases.append(
                    {
                        "test_id": f"{gap['gap_id']}-offline",
                        "purpose": "preserve semantic fit when the external system is unavailable",
                        "arrange": ["deny network and credentials"],
                        "act": "run adapter preflight",
                        "assert": [
                            "typed unavailable_dependency result",
                            "no substitute source is silently selected",
                        ],
                    }
                )
            test_plan = {
                "schema_version": SKILL_TEST_PLAN_SCHEMA,
                "test_plan_id": test_plan_id,
                "gap_id": gap["gap_id"],
                "requirement_id": requirement_id,
                "proposed_component_class": gap["proposed_component_class"],
                "implementation_authorized": False,
                "test_files_written": False,
                "suggested_test_module": f"tests/proposed/test_{gap['gap_id'].replace('-', '_')}.py",
                "test_cases": test_cases,
            }
            test_plan["digest"] = _state_digest(test_plan)
            skill_tests.append(test_plan)
            node = {
                "node_id": f"instantiated-{len(nodes) + 1}",
                "requirement_id": requirement_id,
                "implementation_kind": f"proposed_{gap['proposed_component_class']}",
                "component": None,
                "gap_id": gap["gap_id"],
                "status": "proposed_unavailable",
                "inputs": interface.get("inputs", []),
                "output_type": interface.get("output"),
                "correctness_criteria": interface.get("correctness_criteria", []),
                "test_plan_id": test_plan_id,
                "creation_authorized": False,
            }
        else:
            node = {
                "node_id": f"instantiated-{len(nodes) + 1}",
                "requirement_id": requirement_id,
                "implementation_kind": "unresolved",
                "component": None,
                "status": "blocked_unresolved",
                "inputs": [],
                "output_type": requirement.get("desired_output"),
                "correctness_criteria": list(
                    requirement.get("correctness_criteria", ())
                ),
                "creation_authorized": False,
            }
        node["requirement_ids"] = [requirement_id]
        component_id = (node.get("component") or {}).get("id")
        prior_node = next(
            (
                row
                for row in nodes
                if component_id
                and (row.get("component") or {}).get("id") == component_id
            ),
            None,
        )
        if prior_node is not None:
            prior_node["requirement_ids"].append(requirement_id)
            prior_node["correctness_criteria"] = list(
                dict.fromkeys(
                    [
                        *prior_node.get("correctness_criteria", ()),
                        *node.get("correctness_criteria", ()),
                    ]
                )
            )
            if node.get("status") != "ready":
                prior_node["status"] = node["status"]
            continue
        nodes.append(node)

    formal_ids = " ".join(
        str((node.get("component") or {}).get("id", "")) for node in nodes
    )
    if re.search(
        r"\b(?:autoformalization|bioreason|causal-request|causal-assumption|lean-kernel|open-obligation|checked-claim)\b",
        formal_ids,
    ):

        def instantiated_formal_rank(node: Mapping[str, Any]) -> int:
            """Instantiated formal rank."""
            identifier = str((node.get("component") or {}).get("id", ""))
            if node.get("implementation_kind") == "workflow_composition":
                return 0
            if node.get("implementation_kind") == "workflow_delivery_contract":
                return 100
            if "causal-request" in identifier or "causal-assumption" in identifier:
                return 10
            if any(
                term in identifier
                for term in (
                    "autoformalization-job",
                    "autoformalizer",
                    "premise-selector",
                    "obligation-emitter",
                )
            ):
                return 20
            if "critic" in identifier or "auditor" in identifier:
                return 30
            if "kernel" in identifier or "checker" in identifier:
                return 40
            if "obligation-reporter" in identifier:
                return 50
            if "explainer" in identifier or "rewriter" in identifier:
                return 60
            return 35

        nodes = [
            row
            for _index, row in sorted(
                enumerate(nodes),
                key=lambda item: (instantiated_formal_rank(item[1]), item[0]),
            )
        ]
    else:

        def generic_rank(node: Mapping[str, Any]) -> int:
            """Generic rank."""
            identifier = str((node.get("component") or {}).get("id", ""))
            kind = node.get("implementation_kind")
            if kind == "workflow_composition":
                return 0
            if kind == "workflow_delivery_contract":
                return 100
            if any(
                term in identifier
                for term in ("query", "search", "ingest", "source-scout", "preflight")
            ):
                return 10
            if any(
                term in identifier
                for term in (
                    "normalizer",
                    "stager",
                    "trace",
                    "auditor",
                    "crosswalk",
                    "curator",
                )
            ):
                return 20
            if any(
                term in identifier
                for term in (
                    "critic",
                    "verifier",
                    "gater",
                    "ranker",
                    "statistician",
                    "analyst",
                )
            ):
                return 30
            if any(
                term in identifier
                for term in (
                    "comparability",
                    "assembler",
                    "writer",
                    "rewriter",
                    "reporter",
                    "explainer",
                    "polisher",
                )
            ):
                return 50
            return 40

        nodes = [
            row
            for _index, row in sorted(
                enumerate(nodes), key=lambda item: (generic_rank(item[1]), item[0])
            )
        ]

    operational_nodes = [
        node
        for node in nodes
        if node.get("implementation_kind") != "workflow_composition"
    ]
    upstream_blocked = False
    for node in operational_nodes:
        if upstream_blocked and node.get("status") == "ready":
            node["status"] = "blocked"
        upstream_blocked = upstream_blocked or node.get("status") != "ready"
    edges: list[dict[str, Any]] = []
    for left, right in pairwise(operational_nodes):
        edges.append(
            {
                "edge_id": f"instantiated-edge-{len(edges) + 1}",
                "from_node": left["node_id"],
                "to_node": right["node_id"],
                "artifact_type": left.get("output_type"),
                "compatibility": next(
                    (
                        edge["compatibility"]
                        for edge in workflow_draft.get("edges", ())
                        if edge["from_node"] == f"node-{len(edges) + 1}"
                        and edge["to_node"] == f"node-{len(edges) + 2}"
                    ),
                    "requires_mapping_review",
                ),
                "invented_mapping": False,
            }
        )
    blockers = [
        {
            "requirement_ids": node.get("requirement_ids", [node["requirement_id"]]),
            "status": node["status"],
        }
        for node in nodes
        if node["status"] != "ready"
    ]
    mapping_blockers = [
        edge["edge_id"]
        for edge in edges
        if edge["compatibility"] != "documented_compatible"
    ]
    blockers.extend(
        {"edge_id": edge_id, "status": "requires_mapping_review"}
        for edge_id in mapping_blockers
    )
    covered_requirement_ids = {
        requirement_id
        for node in nodes
        for requirement_id in node.get("requirement_ids", [node["requirement_id"]])
    }
    instantiation = {
        "schema_version": WORKFLOW_INSTANTIATION_SCHEMA,
        "dialogue_id": state["dialogue_id"],
        "turn_index": state["turn_index"],
        "status": (
            "instantiated_ready"
            if not blockers and not mapping_blockers
            else "instantiated_with_blockers"
        ),
        "requirement_coverage_complete": covered_requirement_ids
        == {str(row["requirement_id"]) for row in active_requirements},
        "nodes": nodes,
        "edges": edges,
        "terminal_artifact": state.get("active_inputs", {}).get("terminal_artifact")
        or (operational_nodes[-1].get("output_type") if operational_nodes else None),
        "blockers": blockers,
        "mapping_review_edge_ids": mapping_blockers,
        "proposed_skill_test_plan_ids": [row["test_plan_id"] for row in skill_tests],
        "route_only": True,
        "execution_authorized": False,
    }
    report_inheritance = workflow_draft.get("report_workflow_inheritance")
    if isinstance(report_inheritance, Mapping):
        instantiation["report_workflow_inheritance"] = dict(report_inheritance)
        instantiation.update(project_report_inheritance_plans(report_inheritance))
    instantiation["structure_digest"] = _digest(
        {
            "nodes": nodes,
            "edges": edges,
            "terminal_artifact": instantiation["terminal_artifact"],
            "report_workflow_inheritance": instantiation.get(
                "report_workflow_inheritance"
            ),
            **project_report_inheritance_plans(report_inheritance or {}),
        }
    )
    instantiation["digest"] = _state_digest(instantiation)
    return instantiation, skill_tests


def build_workflow_refinement_cycle(
    state: Mapping[str, Any],
    instantiation: Mapping[str, Any],
    proposed_skill_test_plans: Iterable[Mapping[str, Any]],
    *,
    prior_cycle: Mapping[str, Any] | None = None,
    report_inheritance: Mapping[str, Any] | None = None,
    post_plan_verification: Mapping[str, Any] | None = None,
    answer_control_readiness: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a bounded preflight -> test -> evidence -> repair cycle."""

    findings: list[dict[str, Any]] = []
    tests: list[dict[str, Any]] = []
    nodes = list(instantiation.get("nodes", ()))
    edges = list(instantiation.get("edges", ()))
    if not instantiation.get("requirement_coverage_complete"):
        findings.append(
            {
                "finding_id": "coverage-incomplete",
                "owner": "workflow_instantiation",
                "severity": "critical",
                "repair": "instantiate or explicitly block every active requirement",
            }
        )
    for node in nodes:
        test_id = f"{node['node_id']}-contract-and-output"
        tests.append(
            {
                "test_id": test_id,
                "target": node["node_id"],
                "kind": "node_contract_and_output",
                "required_assertions": [
                    "all required inputs are bound or the node fails closed",
                    *list(node.get("correctness_criteria", ())),
                    "output conforms to the declared artifact type",
                    "provenance and authority remain visible",
                ],
            }
        )
        if node.get("status") != "ready":
            findings.append(
                {
                    "finding_id": f"{node['node_id']}-not-ready",
                    "owner": node["node_id"],
                    "severity": "critical",
                    "status": node.get("status"),
                    "repair": "resolve bindings/authority or implement the governed gap and pass its test plan",
                }
            )
    for edge in edges:
        tests.append(
            {
                "test_id": f"{edge['edge_id']}-handoff",
                "target": edge["edge_id"],
                "kind": "typed_handoff",
                "required_assertions": [
                    "producer artifact type satisfies the consumer input contract",
                    "identity, provenance, and uncertainty survive transport",
                    "no mapping is inferred without reviewed evidence",
                ],
            }
        )
        if edge.get("compatibility") != "documented_compatible":
            findings.append(
                {
                    "finding_id": f"{edge['edge_id']}-mapping-review",
                    "owner": edge["edge_id"],
                    "severity": "critical",
                    "repair": "add and review an explicit typed mapping or revise the node boundary",
                }
            )
    for section in (report_inheritance or {}).get("section_critiques", ()):
        section_id = str(section["section_id"])
        tests.append(
            {
                "test_id": f"report-section-{section_id}",
                "target": f"report-section:{section_id}",
                "kind": "section_scientific_critique",
                "critic_control_ids": list(section.get("critic_control_ids", ())),
                "critic_questions": list(section.get("critic_questions", ())),
                "required_evidence": list(section.get("required_evidence", ())),
                "prohibited_claim": section.get("prohibited_claim"),
                "release_consequence": section.get("release_consequence"),
                "required_assertions": [
                    *list(section.get("critic_questions", ())),
                    str(
                        section.get(
                            "prohibited_claim", "prohibited claims remain absent"
                        )
                    ),
                    "every finding names the affected claim or artifact and its earliest responsible owner",
                    str(
                        section.get(
                            "release_consequence", "critical findings block release"
                        )
                    ),
                ],
            }
        )
    communication_rows = list((report_inheritance or {}).get("communication_plan", ()))
    for phase in ("pre_execution", "during_execution", "post_execution"):
        phase_rows = [row for row in communication_rows if row.get("phase") == phase]
        if not phase_rows:
            continue
        tests.append(
            {
                "test_id": f"researcher-communication-{phase.replace('_', '-')}",
                "target": f"researcher-communication:{phase}",
                "kind": "researcher_methodological_communication",
                "phase": phase,
                "criterion_ids": [str(row["criterion_id"]) for row in phase_rows],
                "required_assertions": [
                    str(row["acceptance_assertion"]) for row in phase_rows
                ],
                "failure_consequences": [
                    str(row["failure_consequence"]) for row in phase_rows
                ],
            }
        )
    # The post-plan verifier is an additive sidecar over the immutable
    # instantiation. Only planned verification checks become execution tests;
    # already-completed deterministic checks stay in the sidecar receipt.
    for specification in (post_plan_verification or {}).get(
        "verification_test_specifications", ()
    ):
        if specification.get("status") != "planned":
            continue
        tests.append(
            {
                "test_id": str(specification["check_id"]),
                "target": str(specification["target"]),
                "kind": f"post_plan_verification:{specification['kind']}",
                "required_assertions": [str(specification["detail"])],
            }
        )
    terminal_test_id = "workflow-terminal-artifact"
    tests.append(
        {
            "test_id": terminal_test_id,
            "target": "workflow",
            "kind": "terminal_artifact",
            "required_assertions": [
                "terminal artifact exists and has the declared type",
                "every active requirement is represented or explicitly blocked",
                "critical uncertainty and prohibited claims are preserved",
            ],
        }
    )
    if not instantiation.get("terminal_artifact"):
        findings.append(
            {
                "finding_id": "terminal-artifact-missing",
                "owner": "workflow",
                "severity": "critical",
                "repair": "bind one terminal artifact to the accepted outcome contract",
            }
        )

    for verification_finding in (post_plan_verification or {}).get("findings", ()):
        if verification_finding.get("severity") not in {"block", "repair"}:
            continue
        findings.append(
            {
                "finding_id": str(verification_finding["finding_id"]),
                "owner": str(
                    verification_finding.get("owner", "post_plan_verification")
                ),
                "severity": (
                    "critical"
                    if verification_finding.get("severity") == "block"
                    else "major"
                ),
                "target": str(verification_finding.get("target", "workflow")),
                "verification_disposition": str(
                    verification_finding.get("disposition", "revise_plan")
                ),
                "repair": str(
                    verification_finding.get(
                        "message", "repair the local verification obligation"
                    )
                ),
            }
        )

    # Score-free answer readiness contributes only prospective receipt tests
    # and local repair proposals. It never converts a planned control into
    # observed evidence or mutates the sealed workflow instantiation.
    for obligation in (answer_control_readiness or {}).get("required_receipts", ()):
        test_id = (
            "answer-trust-receipt-"
            + _digest(
                {
                    "claim_id": obligation.get("claim_id"),
                    "receipt": obligation.get("receipt"),
                }
            ).split(":", 1)[1][:16]
        )
        tests.append(
            {
                "test_id": test_id,
                "target": str(obligation.get("claim_id", "workflow-answer")),
                "kind": "answer_control_readiness:observed_receipt",
                "required_assertions": [
                    f"execution produces an authorized observed receipt for {obligation.get('receipt')}",
                    "the receipt binds the exact answer component and retains prospective-versus-observed polarity",
                ],
            }
        )
    for readiness_finding in (answer_control_readiness or {}).get("findings", ()):
        proposed = readiness_finding.get("proposed_todo", {})
        findings.append(
            {
                "finding_id": str(
                    readiness_finding.get("finding_id", "answer-control-readiness")
                ),
                "owner": str(proposed.get("owner", "answer_control_readiness")),
                "severity": (
                    "major" if readiness_finding.get("severity") == "high" else "minor"
                ),
                "target": str(
                    readiness_finding.get("plan_location") or "workflow-answer"
                ),
                "verification_disposition": "revise_plan",
                "repair": str(
                    proposed.get("action")
                    or readiness_finding.get("message")
                    or "add the missing answer trust control"
                ),
                "acceptance_evidence": proposed.get("acceptance_evidence"),
            }
        )

    gap_test_ids = [
        str(case["test_id"])
        for plan in proposed_skill_test_plans
        for case in plan.get("test_cases", ())
    ]
    required_test_ids = [str(row["test_id"]) for row in tests] + gap_test_ids
    test_targets = {str(row["test_id"]): str(row["target"]) for row in tests}
    test_targets.update(
        {
            str(case["test_id"]): str(plan.get("gap_id", "proposed-capability"))
            for plan in proposed_skill_test_plans
            for case in plan.get("test_cases", ())
        }
    )
    supplied_results = state.get("active_inputs", {}).get("workflow_execution_results")
    result_rows = (
        supplied_results.get("test_results", ())
        if isinstance(supplied_results, Mapping)
        else ()
    )
    result_by_id = {
        str(row.get("test_id")): dict(row)
        for row in result_rows
        if isinstance(row, Mapping) and row.get("test_id")
    }
    structure_digest = str(
        instantiation.get("structure_digest", instantiation["digest"])
    )
    prior_same_structure = (prior_cycle or {}).get(
        "input_instantiation_digest"
    ) == structure_digest
    verified_passes: set[str] = (
        set((prior_cycle or {}).get("verified_test_ids", ()))
        if prior_same_structure
        else set()
    )
    execution_failures: list[dict[str, Any]] = []
    for test_id, row in result_by_id.items():
        evidence = str(row.get("evidence_digest", ""))
        if row.get("status") == "passed" and re.fullmatch(
            r"sha256:[0-9a-f]{64}", evidence
        ):
            verified_passes.add(test_id)
        elif test_id in required_test_ids:
            verified_passes.discard(test_id)
            execution_failures.append(
                {
                    "finding_id": f"execution-{test_id}",
                    "owner": test_id,
                    "severity": "critical",
                    "observed_status": row.get("status", "missing"),
                    "evidence_digest": (
                        evidence
                        if re.fullmatch(r"sha256:[0-9a-f]{64}", evidence)
                        else None
                    ),
                    "expected": next(
                        (
                            item["required_assertions"]
                            for item in tests
                            if item["test_id"] == test_id
                        ),
                        [],
                    ),
                    "observed": row.get("observed", row.get("message")),
                    "repair": "refine the earliest responsible node or edge and rerun this test",
                }
            )
    findings.extend(execution_failures)
    missing_execution_results = sorted(set(required_test_ids) - verified_passes)

    primary = (
        execution_failures[0]
        if execution_failures
        else (findings[0] if findings else None)
    )
    primary_owner = str((primary or {}).get("owner", "workflow"))
    target = test_targets.get(primary_owner, primary_owner)
    if target.startswith("instantiated-edge"):
        layer = "typed_handoff"
        hypotheses = [
            "producer artifact type does not satisfy the consumer contract",
            "mapping lost identity/provenance",
            "consumer boundary is too narrow",
        ]
        minimal_fix = "repair or replace the typed mapping at the failing edge"
    elif target.startswith("instantiated-"):
        layer = "component_or_binding"
        hypotheses = [
            "required input was missing or misbound",
            "selected component contract does not cover the requirement",
            "component implementation did not satisfy its output criteria",
        ]
        minimal_fix = "repair the failing node binding, selection, contract, or implementation without changing verified predecessors"
    elif target.startswith("gap-"):
        layer = "proposed_capability"
        hypotheses = [
            "the proposed capability is not implemented",
            "its interface is incomplete",
            "its correctness criteria are not met",
        ]
        minimal_fix = "implement the governed capability and its test plan, or replace it with proven reuse"
    elif target == "workflow":
        layer = "terminal_artifact"
        hypotheses = [
            "an upstream obligation is absent",
            "terminal assembly lost required content",
            "claim/provenance gates rejected the artifact",
        ]
        minimal_fix = "repair the earliest upstream cause of the terminal failure and rebuild the terminal artifact"
    else:
        layer = "workflow_instantiation"
        hypotheses = [
            "an accepted requirement has no ready owner",
            "an authority or availability gate blocks the plan",
            "the workflow boundary is incomplete",
        ]
        minimal_fix = str(
            (primary or {}).get("repair", "complete the workflow instantiation")
        )
    primary_index = (
        required_test_ids.index(primary_owner)
        if primary_owner in required_test_ids
        else 0
    )
    invalidated_test_ids = required_test_ids[primary_index:] if primary else []
    preserved_test_ids = sorted(verified_passes - set(invalidated_test_ids))
    diagnosis = {
        "status": (
            "evidence_backed"
            if execution_failures and execution_failures[0].get("evidence_digest")
            else ("pre_execution" if primary else "no_failure")
        ),
        "primary_finding_id": (primary or {}).get("finding_id"),
        "localized_target": target if primary else None,
        "layer": layer if primary else None,
        "hypotheses": [
            {
                "rank": index + 1,
                "hypothesis": hypothesis,
                "evidence_for": (
                    [
                        primary.get("observed_status"),
                        primary.get("observed"),
                        primary.get("evidence_digest"),
                    ]
                    if primary
                    else []
                ),
                "evidence_against": [],
                "status": "selected" if index == 0 else "alternative",
            }
            for index, hypothesis in enumerate(hypotheses if primary else [])
        ],
        "selection_rule": "earliest critical execution failure, otherwise earliest pre-execution blocker",
    }
    fix_plan = {
        "status": "required" if primary else "not_required",
        "diagnostic_target": target if primary else None,
        "minimal_fix": minimal_fix if primary else None,
        "preserve_test_ids": preserved_test_ids,
        "invalidate_test_ids": invalidated_test_ids,
        "targeted_rerun_test_ids": sorted(
            set(invalidated_test_ids) | set(missing_execution_results)
        ),
        "broad_rebuild_allowed": False,
        "implementation_authorized": False,
        "acceptance": "all invalidated and previously missing tests return passing content-addressed evidence",
    }

    finalization_phase = state.get("planning_phase") in {
        "ready_for_review",
        "ready_for_delivery",
    }
    prior_iteration = int((prior_cycle or {}).get("iteration", 0))
    has_new_execution_evidence = bool(result_rows)
    instantiation_changed = (prior_cycle or {}).get(
        "input_instantiation_digest"
    ) != structure_digest
    iteration = (
        min(3, prior_iteration + 1)
        if finalization_phase
        and (
            prior_iteration == 0 or has_new_execution_evidence or instantiation_changed
        )
        else prior_iteration
    )
    pre_execution_ready = not findings
    execution_validated = pre_execution_ready and not missing_execution_results
    if not finalization_phase:
        status = "not_started"
    elif execution_validated:
        status = "validated_for_release"
    elif iteration >= 3 and execution_failures:
        status = "escalation_required"
    elif pre_execution_ready:
        status = "ready_for_controlled_execution"
    else:
        status = "blocked_for_refinement"
    cycle = {
        "schema_version": WORKFLOW_REFINEMENT_SCHEMA,
        "dialogue_id": state["dialogue_id"],
        "iteration": iteration,
        "max_iterations": 3,
        "status": status,
        "input_instantiation_digest": structure_digest,
        "pre_execution_ready": pre_execution_ready,
        "execution_validated": execution_validated,
        "findings": findings,
        "diagnostic": diagnosis,
        "fix_plan": fix_plan,
        "repair_actions": [
            {
                "order": index + 1,
                "finding_id": finding["finding_id"],
                "owner": finding["owner"],
                "action": finding["repair"],
                "preserve_verified_test_ids": preserved_test_ids,
            }
            for index, finding in enumerate(findings)
        ],
        "workflow_test_specifications": tests,
        "proposed_skill_test_plan_ids": [
            str(row.get("test_plan_id")) for row in proposed_skill_test_plans
        ],
        "required_test_ids": required_test_ids,
        "verified_test_ids": sorted(verified_passes),
        "missing_execution_test_ids": missing_execution_results,
        "release_gate": (
            "passed" if execution_validated else "blocked_pending_execution_validation"
        ),
        "next_iteration_trigger": (
            "none"
            if execution_validated
            else "new user facts, reviewed implementation, or content-addressed execution-test results"
        ),
        "route_only": True,
        "planner_executed_workflow": False,
    }
    cycle["digest"] = _state_digest(cycle)
    return cycle


def build_elicitation(
    binding: Mapping[str, Any],
    adjudication: Mapping[str, Any],
    state: Mapping[str, Any],
) -> dict[str, Any]:
    """Return at most one material, outcome-level question without route IDs."""

    history = list(state.get("question_history", ()))
    unresolved_existing = next(
        (
            row
            for row in history
            if row.get("status") in {"open", "non_answer", "conflicting"}
            and row.get("blocking")
        ),
        None,
    )
    if unresolved_existing is not None:
        return {
            "schema_version": ELICITATION_SCHEMA,
            "questions": [],
            "unresolved_question_ids": [str(unresolved_existing["question_id"])],
            "repeated_question": False,
            "max_questions_per_turn": 1,
        }
    resolved_fields = set(state.get("active_inputs", {}))
    missing = [
        str(name)
        for name in binding.get("material_missing", ())
        if str(name) not in resolved_fields
    ]
    quality = material_quality_elicitation(
        {"goal": state.get("active_goal", "")}, state
    )
    if missing:
        intent = f"supply:{missing[0]}"
        prompt = f"What information should be used for {missing[0].replace('_', ' ')}?"
        effect = (
            "the answer can change input validity or whether the workflow can proceed"
        )
        missing_fields = [missing[0]]
        # Missing runtime artifacts prevent execution, but they must not stop
        # an explicitly requested persistent workflow from accumulating and
        # routing its remaining responsibilities. The unresolved port remains
        # visible as a non-release blocker on the instantiated node.
        blocking = not bool(
            re.search(
                r"\b(?:workflow|pipeline)\b",
                str(state.get("active_goal", "")),
                flags=re.IGNORECASE,
            )
        )
    elif quality:
        if quality.get("status") == "already_open":
            return {
                "schema_version": ELICITATION_SCHEMA,
                "questions": [],
                "unresolved_question_ids": [str(quality["question_id"])],
                "repeated_question": False,
                "max_questions_per_turn": 1,
            }
        intent = str(quality["intent"])
        prompt = str(quality["prompt"])
        effect = str(quality["expected_decision_effect"])
        missing_fields = list(quality.get("missing_fields", ()))
        blocking = bool(quality.get("blocking"))
    elif adjudication.get("status") == "clarification_required":
        intent = "distinguish:desired_outcome"
        prompt = "Which requested outcome should the workflow prioritize, and what evidence should distinguish it?"
        effect = "the answer can distinguish materially different capability routes"
        missing_fields = ["desired_outcome"]
        blocking = True
    else:
        intent = None
        prompt = None
        effect = None
        missing_fields = []
        blocking = False
    previous = (
        next(
            (
                row
                for row in history
                if row.get("intent") == intent
                and row.get("status") in {"open", "non_answer", "conflicting"}
            ),
            None,
        )
        if intent
        else None
    )
    questions: list[dict[str, Any]] = []
    if intent and previous is None:
        question = {
            "question_id": f"question-{len(history) + 1}",
            "intent": intent,
            "prompt": prompt,
            "expected_decision_effect": effect,
            "source_turn_index": state["turn_index"],
            "status": "open",
            "internal_alternatives_exposed": False,
            "missing_fields": missing_fields,
            "blocking": blocking,
        }
        questions.append(question)
    return {
        "schema_version": ELICITATION_SCHEMA,
        "questions": questions,
        "unresolved_question_ids": [str(previous["question_id"])] if previous else [],
        "repeated_question": False,
        "max_questions_per_turn": 1,
    }


def _continuation(
    frame: Mapping[str, Any],
    snapshot_digest: str,
    missing: list[str],
    alternatives: list[str],
    selected: Mapping[str, Any] | None,
    state: Mapping[str, Any],
    elicitation: Mapping[str, Any],
) -> dict[str, Any]:
    """Continuation."""
    value = {
        "schema_version": CONTINUATION_SCHEMA,
        "context_identity": current_config().context_identity,
        "request_id": frame["digest"],
        "snapshot_digest": snapshot_digest,
        "material_fields": missing,
        "alternatives": alternatives,
        "prior_goal": frame["goal"],
        "prior_selected": dict(selected or {}),
        "response_schema": {
            "type": "object",
            "properties": {name: {} for name in missing},
            "additionalProperties": True,
        },
        "dialogue_state": dict(state),
        "elicitation": dict(elicitation),
    }
    value["digest"] = _digest(value)
    return value


def validate_continuation(envelope: Mapping[str, Any], snapshot_digest: str) -> None:
    """Reject tampered, incompatible, or stale dialogue continuations."""

    supplied = dict(envelope)
    if tuple(supplied.get("context_identity") or ()) != tuple(
        current_config().context_identity or ()
    ):
        raise ValueError("continuation belongs to another owner/package/version")
    digest = supplied.pop("digest", None)
    if digest != _digest(supplied):
        raise ValueError("tampered continuation envelope")
    if supplied.get("schema_version") != CONTINUATION_SCHEMA:
        raise ValueError("unsupported continuation envelope")
    if supplied.get("snapshot_digest") != snapshot_digest:
        raise ValueError("stale planner snapshot")
    state = supplied.get("dialogue_state")
    if state:
        if state.get("schema_version") != DIALOGUE_STATE_SCHEMA:
            raise ValueError("unsupported dialogue state")
        if state.get("snapshot_digest") != snapshot_digest:
            raise ValueError("stale dialogue state")
        if state.get("digest") != _state_digest(state):
            raise ValueError("tampered dialogue state")


_QUALITY_CONTINUATION_INPUTS = frozenset(
    {
        "frozen_outcome_quality_contract",
        "outcome_quality_review",
        "authorized_outcome_quality_review",
        "frozen_delivery_quality_plan",
        "delivery_quality_review",
        "authorized_delivery_quality_review",
    }
)


def _quality_submission(
    supplied_inputs: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Separate orchestration receipts from scientific component inputs."""

    values = dict(supplied_inputs or {})
    quality = {
        key: values.pop(key)
        for key in tuple(values)
        if key in _QUALITY_CONTINUATION_INPUTS
    }
    return values, quality


def _strict_quality_sequence(frame: Mapping[str, Any]) -> bool:
    """Require reviewed freezes for every semantic main-route request.

    Control-plane traffic is handled by :func:`plan_control_request` and uses a
    deterministic, non-semantic quality receipt. Every request that reaches
    semantic routing can eventually produce biomedical content, so risk tier
    is allowed to add scrutiny but never to bypass the two reviewed freezes.
    """

    return classify_quality_policy(frame)["tier"] != "control"


def _reviewed_provisional_digest(frozen: Mapping[str, Any]) -> str:
    """Recover the exact provisional bytes that a freeze is allowed to derive from."""

    provisional = dict(frozen)
    provisional["lifecycle"] = "provisional"
    provisional["review_status"] = "pending"
    provisional["criteria"] = [
        {**dict(row), "lifecycle": "provisional"} for row in frozen.get("criteria", ())
    ]
    return canonical_digest(provisional)


def _accept_frozen_quality_plan(
    frozen: Mapping[str, Any] | None,
    review: Mapping[str, Any] | None,
    authorized_review: Mapping[str, Any] | None,
    *,
    schema_version: str,
    root_interaction_id: str,
    principal: Mapping[str, Any],
    parent_digest: str | None = None,
    outcome_contract_digest: str | None = None,
) -> dict[str, Any] | None:
    """Validate an independently reviewed freeze without trusting caller labels."""

    if frozen is None and review is None and authorized_review is None:
        return None
    if (
        not isinstance(frozen, Mapping)
        or not isinstance(review, Mapping)
        or not isinstance(authorized_review, Mapping)
    ):
        raise ValueError(
            "a frozen quality plan, independent review, and authenticated review package are required"
        )
    plan_report = validate_contract(frozen)
    review_report = validate_contract(review)
    if not plan_report.valid:
        raise ValueError(
            f"invalid frozen quality plan: {'; '.join(plan_report.errors)}"
        )
    if not review_report.valid:
        raise ValueError(
            f"invalid quality-plan review: {'; '.join(review_report.errors)}"
        )
    if (
        frozen.get("schema_version") != schema_version
        or frozen.get("lifecycle") != "frozen"
    ):
        raise ValueError("quality continuation requires the expected frozen plan type")
    if review.get("verdict") != "pass" or review.get("independent") is not True:
        raise ValueError("quality continuation requires an independent passing review")
    if review.get("plan_digest") != frozen.get(
        "reviewed_plan_digest", _reviewed_provisional_digest(frozen)
    ):
        raise ValueError(
            "frozen quality plan does not derive from the reviewed provisional bytes"
        )
    if frozen.get("root_interaction_id") != root_interaction_id:
        raise ValueError("quality continuation changed the root interaction")
    if dict(frozen.get("principal", {})) != dict(principal):
        raise ValueError("quality continuation changed the authorized principal")
    trusted_key = os.environ.get("LUNAR_QUALITY_ATTESTATION_KEY", "").encode()
    verify_signed_quality_receipt(
        authorized_review,
        trusted_key,
        "authorized quality-plan review",
    )
    if (
        authorized_review.get("schema_version")
        != "lunar.planner.authorized-quality-plan-review/v1"
    ):
        raise ValueError("quality continuation has an unsupported review authorization")
    if authorized_review.get("quality_plan_digest") != review.get("plan_digest"):
        raise ValueError("authorized review package binds a different provisional plan")
    if authorized_review.get("reviewer") != review.get("reviewer"):
        raise ValueError("authorized review package binds a different reviewer")
    producer_id = str(authorized_review.get("criterion_producer_id", ""))
    reviewer_id = str((review.get("reviewer") or {}).get("id", ""))
    if not producer_id or not reviewer_id or producer_id == reviewer_id:
        raise ValueError(
            "authorized review package does not establish reviewer separation"
        )
    semantic_review = authorized_review.get("semantic_review")
    if not isinstance(semantic_review, Mapping):
        raise ValueError("authorized review package lacks its semantic review")
    if (
        semantic_review.get("plan_digest") != review.get("plan_digest")
        or semantic_review.get("reviewer_id") != reviewer_id
        or semantic_review.get("independent") is not True
        or semantic_review.get("verdict") != "pass"
    ):
        raise ValueError("authorized review package does not match the passing review")
    required_repetitions = (
        2 if frozen.get("risk_tier") in {"complex", "human_authority"} else 1
    )
    if not plan_review_evaluation_receipts_sufficient(
        semantic_review,
        required_repetitions=required_repetitions,
        criterion_producer_id=producer_id,
        reviewer=(
            review.get("reviewer")
            if isinstance(review.get("reviewer"), Mapping)
            else None
        ),
    ):
        raise ValueError(
            "authorized review package lacks the policy-required independent repetitions"
        )
    if parent_digest is not None and frozen.get("parent_digest") != parent_digest:
        raise ValueError("quality continuation is not bound to the exact request frame")
    if (
        outcome_contract_digest is not None
        and frozen.get("outcome_contract_digest") != outcome_contract_digest
    ):
        raise ValueError(
            "delivery quality plan is not bound to the frozen outcome contract"
        )
    return dict(frozen)


def _unrouted_workflow_draft(
    state: Mapping[str, Any], ledger: Mapping[str, Any]
) -> dict[str, Any]:
    """Represent framed obligations without consulting or naming catalog routes."""

    draft = {
        "schema_version": WORKFLOW_DRAFT_SCHEMA,
        "dialogue_id": state["dialogue_id"],
        "turn_index": state["turn_index"],
        # Keep the workflow lifecycle valid while quality has its own explicit
        # checkpoint state.  This is a framed, deliberately unrouted draft.
        "status": "framing",
        "nodes": [],
        "edges": [],
        "gates": [{"gate": "outcome_quality_freeze", "status": "blocked"}],
        "critics": ["independent_outcome_quality_plan_review"],
        "terminal_artifact": state.get("active_inputs", {}).get("terminal_artifact"),
        "unresolved_requirement_ids": [
            str(row["requirement_id"])
            for row in ledger.get("requirements", ())
            if row.get("status") == "active"
        ],
        "route_only": True,
    }
    draft["digest"] = _state_digest(draft)
    return draft


def _quality_checkpoint_continuation(
    frame: Mapping[str, Any],
    snapshot_digest: str,
    state: Mapping[str, Any],
    *,
    phase: str,
    outcome_contract: Mapping[str, Any],
    delivery_plan: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Quality checkpoint continuation."""
    value = {
        "schema_version": CONTINUATION_SCHEMA,
        "context_identity": current_config().context_identity,
        "request_id": frame["digest"],
        "snapshot_digest": snapshot_digest,
        "material_fields": [],
        "alternatives": [],
        "prior_goal": frame["goal"],
        "prior_selected": {},
        "response_schema": {"type": "object", "additionalProperties": True},
        "dialogue_state": dict(state),
        "elicitation": {
            "schema_version": ELICITATION_SCHEMA,
            "questions": [],
            "unresolved_question_ids": [],
            "repeated_question": False,
            "max_questions_per_turn": 0,
        },
        "quality_checkpoint": {
            "phase": phase,
            "frame": dict(frame),
            "requirement_ledger_digest": state["requirement_ledger"]["digest"],
            "principal": dict(outcome_contract["principal"]),
            "outcome_contract": dict(outcome_contract),
            "delivery_plan": dict(delivery_plan) if delivery_plan is not None else None,
        },
    }
    value["digest"] = _digest(value)
    return value


def _quality_wait_receipt(
    *,
    frame: Mapping[str, Any],
    surface: Mapping[str, Any],
    snapshot_digest: str,
    state: Mapping[str, Any],
    requirement_ledger: Mapping[str, Any],
    outcome_contract: Mapping[str, Any],
    outcome_review: Mapping[str, Any],
    phase: str,
    test_snapshot: bool,
    delivery_plan: Mapping[str, Any] | None = None,
    delivery_review: Mapping[str, Any] | None = None,
    elicitation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Emit a sealed, deliberately non-routed checkpoint receipt."""

    draft = _unrouted_workflow_draft(state, requirement_ledger)
    state = dict(state)
    intent_clarification = phase == "quality_intent_clarification_required"
    state["quality_phase"] = phase
    if intent_clarification:
        state["planning_phase"] = "eliciting"
        draft["status"] = "eliciting"
        draft["digest"] = _state_digest(draft)
    state["workflow_draft"] = draft
    state["requirement_ledger"] = dict(requirement_ledger)
    if frame.get("persistent_change_requested") and not state.get(
        "workflow_refinement_cycle"
    ):
        # A quality freeze blocks routing, but it must not hide the execution
        # validation gate from workflow-building clients.  Materialize a
        # schema-valid pre-routing cycle over an explicitly unavailable
        # instantiation so callers can see that release remains blocked.
        provisional_instantiation = {
            "digest": _digest(
                {
                    "dialogue_id": state["dialogue_id"],
                    "phase": phase,
                    "status": "not_instantiated_before_outcome_freeze",
                }
            ),
            "requirement_coverage_complete": False,
            "nodes": [],
            "edges": [],
            "terminal_artifact": None,
        }
        state["workflow_refinement_cycle"] = build_workflow_refinement_cycle(
            state,
            provisional_instantiation,
            state.get("proposed_skill_test_plans", ()),
            prior_cycle=None,
        )
    state["current_stage_digest"] = _digest(
        {
            "request_frame": frame,
            "requirement_ledger": requirement_ledger,
            "outcome_quality_contract": outcome_contract,
            "delivery_quality_plan": delivery_plan,
            "phase": phase,
        }
    )
    state["digest"] = _state_digest(state)
    elicitation_value = dict(
        elicitation
        or {
            "schema_version": ELICITATION_SCHEMA,
            "questions": [],
            "unresolved_question_ids": [],
            "repeated_question": False,
            "max_questions_per_turn": 0,
        }
    )
    continuation = (
        _continuation(
            frame,
            snapshot_digest,
            [],
            [],
            None,
            state,
            elicitation_value,
        )
        if intent_clarification
        else _quality_checkpoint_continuation(
            frame,
            snapshot_digest,
            state,
            phase=phase,
            outcome_contract=outcome_contract,
            delivery_plan=delivery_plan,
        )
    )
    quality_handoff = {
        "schema_version": "lunar.planner.contextual-quality-handoff/v1",
        "outcome_contract_digest": outcome_contract["digest"],
        "delivery_plan_digest": delivery_plan["digest"] if delivery_plan else None,
        "must_pass_criterion_ids": [
            row["criterion_id"]
            for row in (delivery_plan or outcome_contract).get("criteria", ())
            if row.get("severity") == "must_pass"
        ],
        "evidence_whitelist": list(
            (delivery_plan or outcome_contract).get("evidence_whitelist", ())
        ),
        "risk_tier": outcome_contract["risk_tier"],
        "assessment_required": False,
        "independent_quality_validation_required": True,
        "release_authorized": False,
        "route_only": True,
    }
    quality_handoff["digest"] = _digest(quality_handoff)
    prior_instantiation = state.get("workflow_instantiation")
    if prior_instantiation:
        prior_instantiation = json.loads(json.dumps(prior_instantiation))
        terminal = state.get("active_inputs", {}).get("terminal_artifact")
        if terminal and prior_instantiation.get("nodes"):
            prior_instantiation["terminal_artifact"] = terminal
            prior_instantiation["nodes"][-1]["output_type"] = terminal
            prior_instantiation["digest"] = _state_digest(prior_instantiation)
    receipt = {
        "schema_version": RECEIPT_SCHEMA,
        "request_frame": dict(frame),
        "catalog_snapshot": {
            "schema_version": surface.get("schema_version"),
            "digest": snapshot_digest,
            "test_snapshot": test_snapshot,
        },
        "retrieval": {"status": "not_started_before_outcome_freeze", "candidates": []},
        "adjudication": {"status": "not_started", "selected": None, "rejected": []},
        "decomposition": [
            {
                "unit": {
                    "index": index,
                    "text": row.get("active_text", row.get("text", "")),
                    "requirement_id": row["requirement_id"],
                },
                "disposition": "framed_not_routed",
                "selected": None,
                "serious_alternatives": [],
            }
            for index, row in enumerate(requirement_ledger.get("requirements", ()))
            if row.get("status") == "active"
        ],
        "dialogue_state": state,
        "requirement_ledger": dict(requirement_ledger),
        "workflow_draft": draft,
        "workflow_instantiation": prior_instantiation,
        "proposed_skill_test_plans": list(state.get("proposed_skill_test_plans", ())),
        "workflow_refinement_cycle": state.get("workflow_refinement_cycle"),
        "selected_targets": [],
        "binding": {"status": "not_started", "ports": [], "material_missing": []},
        "preflight": {
            "fit_status": "not_selected",
            "availability_status": "not_checked",
            "authority_status": "not_checked",
            "posture": None,
            "claim_ceiling": None,
        },
        "disposition": "clarification_required" if intent_clarification else phase,
        "primary_failure_owner": "quality_planning",
        "continuation": continuation,
        "elicitation": elicitation_value,
        "delivery_handoff": None,
        "capability_gap_plan": state.get("capability_gap_plan"),
        "outcome_quality_contract": dict(outcome_contract),
        "outcome_quality_review": dict(outcome_review),
        "delivery_quality_plan": dict(delivery_plan) if delivery_plan else None,
        "delivery_quality_review": dict(delivery_review) if delivery_review else None,
        "quality_handoff": quality_handoff,
        "quality_disposition": phase,
        "route_only": True,
    }
    reasoning_log = build_reasoning_log(
        subject_kind="planner",
        subject_id=f"{state['dialogue_id']}:turn-{state['turn_index']}",
        summary=(
            "Lunar framed the request and paused component routing until "
            f"the contextual quality contract reaches {phase}."
        ),
        status="blocked",
        events=[
            {
                "stage": "intent and requirement framing",
                "action": "Represented the user request as active requirements.",
                "rationale_summary": "The planner preserves user intent before selecting implementation components.",
                "decision": {
                    "status": "accepted",
                    "outcome": f"{len(receipt['decomposition'])} active obligation(s) framed.",
                },
                "outputs": ["request frame", "requirement ledger"],
                "checks": ["dialogue lineage retained"],
            },
            {
                "stage": "reuse discovery and adjudication",
                "action": "Deferred capability routing until outcome-specific quality criteria are frozen.",
                "rationale_summary": "Premature component selection could optimize for an underspecified result.",
                "decision": {
                    "status": "deferred",
                    "outcome": "No reusable target selected yet.",
                },
                "outputs": ["quality-gated routing disposition"],
                "checks": [
                    "routing starts only after the outcome contract is reviewable"
                ],
            },
            {
                "stage": "workflow instantiation and refinement",
                "action": "Kept workflow construction blocked while requesting the missing quality decision.",
                "rationale_summary": "A workflow must be testable against contextual acceptance criteria before release.",
                "decision": {"status": "blocked", "outcome": phase},
                "outputs": ["continuation checkpoint", "quality handoff"],
                "checks": list(quality_handoff["must_pass_criterion_ids"]),
            },
        ],
        assumptions=state.get("assumptions", ()),
        evidence_references=[
            {
                "id": "catalog-snapshot",
                "kind": "catalog_snapshot",
                "locator": "planner catalog snapshot",
                "digest": snapshot_digest,
            }
        ],
        limitations=[
            "This is a decision trace, not hidden chain-of-thought.",
            "No skill or workflow has executed.",
        ],
    )
    receipt["reasoning_log"] = reasoning_log
    receipt["reasoning_log_markdown"] = render_reasoning_log_markdown(reasoning_log)
    receipt["digest"] = _digest(receipt)
    return receipt


def plan_stages(
    command_text: str,
    surface: Mapping[str, Any],
    *,
    references: Iterable[str] = (),
    desired_inputs: Iterable[str] = (),
    desired_outputs: Iterable[str] = (),
    supplied_inputs: Mapping[str, Any] | None = None,
    authority_envelope: Mapping[str, Any] | None = None,
    continuation: Mapping[str, Any] | None = None,
    exact_route_hint: str | None = None,
    routing_mode_hint: str | None = None,
    verification_context: Mapping[str, Any] | None = None,
    answer_trust_readiness_enabled: bool = False,
    answer_trust_rollout_state: str = "off",
    workflow_economics_enabled: bool = False,
    workflow_economics_mode: str = "off",
    workflow_economics_rollout_state: str = "off",
    workflow_economics_comparator: Mapping[str, Any] | None = None,
    workflow_economics_workload_manifest: Mapping[str, Any] | None = None,
    workflow_economics_resource_profile: Mapping[str, Any] | None = None,
    test_snapshot: bool = False,
) -> dict[str, Any]:
    """Run every non-executing planner-owned stage and seal its receipt."""

    snapshot_digest = _digest(surface)
    scientific_inputs, quality_submission = _quality_submission(supplied_inputs)
    if continuation:
        validate_continuation(continuation, snapshot_digest)
    prior_state = continuation.get("dialogue_state") if continuation else None
    checkpoint_envelope = (
        continuation.get("quality_checkpoint") if continuation else None
    )
    # A checkpoint resumes only when the caller supplies the corresponding
    # independently reviewed quality documents. A normal expert turn is intent
    # evolution: reduce it into dialogue state, invalidate the old provisional
    # bar, and issue a new pre-route outcome checkpoint.
    quality_checkpoint = checkpoint_envelope if quality_submission else None
    if quality_checkpoint:
        assert continuation is not None
        frame = dict(quality_checkpoint["frame"])
        state = dict(continuation["dialogue_state"])
        requirement_ledger = dict(state["requirement_ledger"])
        if requirement_ledger.get("digest") != quality_checkpoint.get(
            "requirement_ledger_digest"
        ):
            raise ValueError(
                "quality continuation changed the framed requirement ledger"
            )
        outcome_quality_seed = dict(quality_checkpoint["outcome_contract"])
        if outcome_quality_seed.get("parent_digest") != frame.get("digest"):
            raise ValueError("quality continuation changed its request-frame binding")
    else:
        state = reduce_dialogue_state(
            command_text,
            snapshot_digest=snapshot_digest,
            supplied_inputs=scientific_inputs,
            references=references,
            authority_envelope=authority_envelope,
            prior_state=prior_state,
        )
        frame = normalize_request(
            state["active_goal"],
            references=state["references"],
            desired_inputs=desired_inputs,
            desired_outputs=desired_outputs,
            supplied_inputs=state["active_inputs"],
        )
        frame.update(
            current_utterance=command_text.strip(),
            dialogue_id=state["dialogue_id"],
            turn_index=state["turn_index"],
            authority=state["authority"],
        )
        frame["digest"] = _digest(
            {key: value for key, value in frame.items() if key != "digest"}
        )
        requirement_ledger = dict(state["requirement_ledger"])
        outcome_quality_seed = build_outcome_quality_contract(
            frame,
            requirement_ledger,
            principal={
                "id": str(
                    state.get("authority", {}).get("principal", "bioagents-user")
                ),
                "kind": "user",
            },
        )
        if exact_route_hint:
            state["exact_route_hint"] = str(exact_route_hint)
        if routing_mode_hint:
            state["entrypoint_mode"] = str(routing_mode_hint)
    if "execution_target" not in state and verification_context:
        source_plans = list(
            (verification_context.get("external_source_plan") or {}).get(
                "query_plans", ()
            )
        )
        if len(source_plans) == 1:
            source_plan = source_plans[0]
            if source_plan.get("resource_id") and source_plan.get("selected_skill_id"):
                state["execution_target"] = {
                    "id": source_plan["resource_id"],
                    "kind": "source",
                    "operation": source_plan.get("operation"),
                    "requested_mode": "fixture_replay",
                    "bound_reader_id": source_plan["selected_skill_id"],
                }
    if not quality_checkpoint:
        state["question_history"] = update_quality_question_states(
            state.get("question_history", ()),
            turn_index=state["turn_index"],
            supplied_inputs=dict(scientific_inputs),
            utterance=command_text,
        )
        non_answer = bool(
            re.search(
                r"\b(?:do not know|don't know|not available|unavailable|still (?:being )?"
                r"(?:assembled|decided|collected)|cannot answer|unsure)\b",
                command_text,
                flags=re.IGNORECASE,
            )
        )
        for question in state["question_history"]:
            intent = str(question.get("intent", ""))
            if (
                question.get("status") == "open"
                and intent.startswith("supply:")
                and intent.split(":", 1)[1] in state.get("active_inputs", {})
            ):
                question["status"] = "resolved"
                question["resolved_turn_index"] = state["turn_index"]
            if (
                question.get("status") == "open"
                and question.get("intent") == "distinguish:desired_outcome"
                and state["turn_index"] > int(question.get("source_turn_index", 0))
                and not non_answer
            ):
                question["status"] = "resolved"
                question["resolved_turn_index"] = state["turn_index"]
        intent_elicitation = build_elicitation(
            {"status": "complete", "material_missing": []},
            {"status": "not_started"},
            state,
        )
        state["question_history"].extend(intent_elicitation["questions"])
        blocking_question_ids = {
            str(question.get("question_id"))
            for question in state["question_history"]
            if question.get("blocking")
            and question.get("status") in {"open", "non_answer", "conflicting"}
        }
        # Execution-input questions for a persistent workflow are deliberately
        # non-blocking: they remain visible as preflight gates, while later
        # dialogue turns can still add and route scientific responsibilities.
        # Only an unresolved question whose contract explicitly marks it as
        # blocking may stop the pre-route quality protocol.
        if any(
            question.get("blocking") for question in intent_elicitation["questions"]
        ) or blocking_question_ids.intersection(
            map(str, intent_elicitation["unresolved_question_ids"])
        ):
            return _quality_wait_receipt(
                frame=frame,
                surface=surface,
                snapshot_digest=snapshot_digest,
                state=state,
                requirement_ledger=requirement_ledger,
                outcome_contract=outcome_quality_seed,
                outcome_review=review_quality_plan(
                    outcome_quality_seed, independent=False
                ),
                phase="quality_intent_clarification_required",
                test_snapshot=test_snapshot,
                elicitation=intent_elicitation,
            )
    outcome_quality_review = review_quality_plan(
        outcome_quality_seed, independent=False
    )
    outcome_quality_contract = outcome_quality_seed
    # All semantic requests use the same resumable two-freeze protocol. A
    # normal utterance at a checkpoint is still intent evolution rather than an
    # implicit approval: the old provisional plan is invalidated and reframed.
    strict_quality = bool(quality_checkpoint) or _strict_quality_sequence(frame)
    if strict_quality:
        if (
            quality_checkpoint
            and quality_checkpoint.get("phase") == "delivery_quality_planning_required"
            and outcome_quality_seed.get("lifecycle") == "frozen"
        ):
            if not validate_contract(outcome_quality_seed).valid:
                raise ValueError(
                    "quality continuation contains an invalid frozen outcome contract"
                )
            accepted_outcome = dict(outcome_quality_seed)
        else:
            accepted_outcome = _accept_frozen_quality_plan(
                quality_submission.get("frozen_outcome_quality_contract"),
                quality_submission.get("outcome_quality_review"),
                quality_submission.get("authorized_outcome_quality_review"),
                schema_version=OUTCOME_QUALITY_SCHEMA,
                root_interaction_id=outcome_quality_seed["root_interaction_id"],
                principal=outcome_quality_seed["principal"],
                parent_digest=frame["digest"],
            )
        if accepted_outcome is None:
            return _quality_wait_receipt(
                frame=frame,
                surface=surface,
                snapshot_digest=snapshot_digest,
                state=state,
                requirement_ledger=requirement_ledger,
                outcome_contract=outcome_quality_seed,
                outcome_review=outcome_quality_review,
                phase="quality_planning_required",
                test_snapshot=test_snapshot,
            )
        if set(map(str, accepted_outcome.get("requirement_ids", ()))) != {
            str(row["requirement_id"])
            for row in requirement_ledger.get("requirements", ())
            if row.get("status") == "active"
        }:
            raise ValueError(
                "frozen outcome contract does not cover the exact active requirement set"
            )
        outcome_quality_contract = accepted_outcome
        if "outcome_quality_review" in quality_submission:
            outcome_quality_review = dict(quality_submission["outcome_quality_review"])

    # Strict requests reach catalog-dependent workflow drafting only after the
    # exact pre-route outcome contract has passed an independent freeze.
    requirement_ledger, workflow_draft = build_workflow_draft(state, frame, surface)
    report_inheritance = build_report_workflow_inheritance(
        state["active_goal"],
        surface,
        references=state.get("references", ()),
        desired_outputs=frame.get("desired_artifacts", ()),
    )
    if report_inheritance is not None:
        workflow_draft["report_workflow_inheritance"] = report_inheritance
        workflow_draft.update(project_report_inheritance_plans(report_inheritance))
        workflow_draft["digest"] = _state_digest(workflow_draft)
    if frame["persistent_change_requested"]:
        semantic_utterance = str(frame.get("current_utterance", command_text))
        closure_requested = bool(
            re.search(
                r"\b(?:finalize|finalise|freeze|produce|return|give me|deliver|ready for review)\b",
                semantic_utterance,
                flags=re.IGNORECASE,
            )
        )
        continuing_refinement = bool(
            ((prior_state or {}).get("workflow_refinement_cycle") or {}).get(
                "iteration", 0
            )
            and state.get("active_inputs", {}).get("workflow_execution_results")
        )
        closure_requested = closure_requested or continuing_refinement
        if closure_requested:
            for requirement in requirement_ledger["requirements"]:
                if requirement.get("status") == "active":
                    requirement["stability"] = "stable"
            requirement_ledger["digest"] = _state_digest(requirement_ledger)
        if state["turn_index"] == 1 and not closure_requested:
            state["planning_phase"] = "framing"
        elif closure_requested and not workflow_draft["unresolved_requirement_ids"]:
            state["planning_phase"] = "ready_for_delivery"
        elif closure_requested:
            state["planning_phase"] = "ready_for_review"
        else:
            state["planning_phase"] = "draft_workflow"
        workflow_draft["status"] = state["planning_phase"]
        workflow_draft["digest"] = _state_digest(workflow_draft)
    else:
        state["planning_phase"] = (
            "ready_for_delivery"
            if not workflow_draft["unresolved_requirement_ids"]
            else "eliciting"
        )
    state["requirement_ledger"] = requirement_ledger
    state["workflow_draft"] = workflow_draft
    workflow_planning_requested = frame["persistent_change_requested"] or bool(
        re.search(
            r"\b(?:workflow|pipeline)\b",
            state.get("active_goal", ""),
            flags=re.IGNORECASE,
        )
    )
    capability_gap_plan = (
        plan_capability_gaps(
            frame,
            surface,
            requirement_rows=requirement_ledger["requirements"],
            prior_plan=(prior_state or {}).get("capability_gap_plan"),
        )
        if workflow_planning_requested
        else None
    )
    state["capability_gap_plan"] = capability_gap_plan
    workflow_instantiation, proposed_skill_test_plans = instantiate_workflow(
        state,
        requirement_ledger,
        workflow_draft,
        capability_gap_plan,
    )
    state["workflow_instantiation"] = workflow_instantiation
    state["proposed_skill_test_plans"] = proposed_skill_test_plans
    post_plan_evidence_verification = build_post_plan_verification(
        workflow_instantiation,
        requirement_ledger,
        verification_context=verification_context,
        enabled=bool(frame["persistent_change_requested"]),
    )
    if post_plan_evidence_verification is not None:
        state["post_plan_evidence_verification"] = post_plan_evidence_verification
    answer_trust_rollout = resolve_answer_trust_rollout(answer_trust_rollout_state)
    answer_control_readiness = (
        build_answer_control_readiness(
            workflow_instantiation,
            post_plan_evidence_verification,
        )
        if (answer_trust_readiness_enabled or answer_trust_rollout["readiness_enabled"])
        and post_plan_evidence_verification is not None
        else None
    )
    if answer_control_readiness is not None:
        state["answer_control_readiness"] = answer_control_readiness
    answer_control_readiness_card = (
        build_readiness_card(
            answer_control_readiness,
            rollout_state=(
                answer_trust_rollout_state
                if answer_trust_rollout_state != "off"
                else "fixture"
            ),
        )
        if answer_control_readiness is not None
        else None
    )
    if answer_control_readiness_card is not None:
        state["answer_control_readiness_card"] = answer_control_readiness_card
    if workflow_economics_mode not in {"off", "estimate", "observe", "budget"}:
        raise ValueError(
            "workflow_economics_mode must be off, estimate, observe, or budget"
        )
    if workflow_economics_mode in {"observe", "budget"}:
        raise ValueError(
            "observed economics and budget mutation require the explicit authorized "
            "host APIs; the planning-only entrypoint can produce estimates only"
        )
    economics_rollout = resolve_workflow_economics_rollout(
        workflow_economics_rollout_state
    )
    economics_requested = bool(
        workflow_economics_enabled
        or workflow_economics_mode != "off"
        or economics_rollout["estimation_enabled"]
    )
    workflow_workload_inventory = None
    workflow_effort_estimate = None
    workflow_resource_estimate = None
    workflow_effort_card = None
    workflow_economics_report = None
    if economics_requested:
        workflow_workload_inventory = compile_work_units(
            workflow_instantiation,
            workflow_economics_workload_manifest,
        )
        workflow_effort_estimate = estimate_workflow_effort(
            workflow_economics_comparator or {},
            workflow_workload_inventory,
            samples=256,
        )
        workflow_resource_estimate = estimate_workflow_resources(
            workflow_instantiation,
            workflow_workload_inventory["work_units"],
            workflow_economics_resource_profile,
        )
        workflow_effort_card = build_workflow_effort_card(workflow_effort_estimate)
        workflow_economics_report = build_workflow_economics_report(
            workflow_effort_estimate,
            workflow_resource_estimate,
            rollout_state=(
                workflow_economics_rollout_state
                if workflow_economics_rollout_state != "off"
                else "fixture"
            ),
        )
        state.update(
            workflow_workload_inventory=workflow_workload_inventory,
            workflow_effort_estimate=workflow_effort_estimate,
            workflow_resource_estimate=workflow_resource_estimate,
            workflow_effort_card=workflow_effort_card,
            workflow_economics_report=workflow_economics_report,
        )
    workflow_refinement_cycle = build_workflow_refinement_cycle(
        state,
        workflow_instantiation,
        proposed_skill_test_plans,
        prior_cycle=(prior_state or {}).get("workflow_refinement_cycle"),
        report_inheritance=report_inheritance,
        post_plan_verification=post_plan_evidence_verification,
        answer_control_readiness=answer_control_readiness,
    )
    state["workflow_refinement_cycle"] = workflow_refinement_cycle
    if (
        frame["persistent_change_requested"]
        and state["planning_phase"] == "ready_for_delivery"
        and workflow_refinement_cycle["status"] != "validated_for_release"
    ):
        state["planning_phase"] = workflow_refinement_cycle["status"]
    retrieval = gather_candidates(
        frame,
        surface,
        exact_route_hint=str(state.get("exact_route_hint") or "") or None,
    )
    adjudication = adjudicate(
        frame,
        retrieval,
        exact_route_hint=str(state.get("exact_route_hint") or "") or None,
    )
    decomposition = [
        {
            "unit": {
                "index": index,
                "text": row.get("active_text", row.get("text", "")),
                "requirement_id": row["requirement_id"],
            },
            "disposition": row.get("planner_decision", {}).get(
                "disposition", "not_active"
            ),
            "selected": row.get("planner_decision", {}).get("selected"),
            "serious_alternatives": row.get("planner_decision", {}).get(
                "serious_alternatives", []
            ),
        }
        for index, row in enumerate(requirement_ledger["requirements"])
        if row.get("status") == "active"
    ]
    selected_targets: list[dict[str, Any]] = []
    seen_targets: set[str] = set()
    for row in decomposition:
        selected = row.get("selected")
        if selected and selected["id"] not in seen_targets:
            seen_targets.add(selected["id"])
            selected_targets.append(selected)
    if not selected_targets and adjudication.get("selected"):
        selected_targets.append(adjudication["selected"])
    selected_id = (adjudication.get("selected") or {}).get("id")
    candidate = next(
        (row for row in retrieval["candidates"] if row["id"] == selected_id), None
    )
    contract = candidate.get("contract") if candidate else None
    binding = (
        bind_inputs(frame, contract)
        if selected_id
        else {"status": "not_started", "ports": [], "material_missing": []}
    )
    preflight_result = preflight(
        adjudication.get("selected"), contract, state["authority"]
    )
    quality_policy = classify_quality_policy(frame)
    denied_authority = set(map(str, state["authority"].get("denied_permissions", ())))
    if (
        quality_policy["tier"] == "human_authority"
        and "clinical_decision" in denied_authority
    ):
        preflight_result["authority_status"] = "denied"
        preflight_result["denied_permissions"] = sorted(
            denied_authority & {"clinical_decision", "regulatory_decision"}
        )
    delivery_quality_seed = build_delivery_quality_plan(
        outcome_quality_contract,
        adjudication.get("selected"),
        binding,
    )
    delivery_quality_review = review_quality_plan(
        delivery_quality_seed, independent=False
    )
    delivery_quality_plan = delivery_quality_seed
    delivery_quality_frozen = False
    if strict_quality:
        accepted_delivery = _accept_frozen_quality_plan(
            quality_submission.get("frozen_delivery_quality_plan"),
            quality_submission.get("delivery_quality_review"),
            quality_submission.get("authorized_delivery_quality_review"),
            schema_version=DELIVERY_QUALITY_SCHEMA,
            root_interaction_id=outcome_quality_contract["root_interaction_id"],
            principal=outcome_quality_contract["principal"],
            outcome_contract_digest=outcome_quality_contract["digest"],
        )
        if accepted_delivery is not None:
            expected_target = (adjudication.get("selected") or {}).get("id")
            accepted_target = (accepted_delivery.get("selected_target") or {}).get("id")
            if accepted_target != expected_target:
                raise ValueError("frozen delivery plan changed the selected route")
            delivery_quality_plan = accepted_delivery
            delivery_quality_review = dict(
                quality_submission["delivery_quality_review"]
            )
            delivery_quality_frozen = True
    disposition = adjudication["status"]
    owner = "adjudication"
    if disposition == "selected" and binding["status"] != "complete":
        disposition, owner = "clarification_required", "binding"
    elif disposition == "selected" and (
        preflight_result["availability_status"] != "available"
        or preflight_result["authority_status"] != "allowed"
    ):
        disposition, owner = "blocked", "preflight"
    elif disposition == "selected":
        disposition, owner = "ready_for_delivery", "dispatch"
    if (
        quality_policy["tier"] == "human_authority"
        and preflight_result["authority_status"] == "denied"
    ):
        disposition, owner = "blocked", "preflight"
    if (
        frame["persistent_change_requested"]
        and disposition == "ready_for_delivery"
        and state["planning_phase"] != "ready_for_delivery"
    ):
        disposition, owner = state["planning_phase"], "dispatch"
    if frame["persistent_change_requested"]:
        refinement_status = workflow_refinement_cycle["status"]
        if refinement_status == "validated_for_release":
            disposition, owner = "ready_for_delivery", "dispatch"
        elif refinement_status == "ready_for_controlled_execution":
            disposition, owner = "ready_for_controlled_execution", "workflow_refinement"
        else:
            disposition, owner = "blocked_for_refinement", "workflow_refinement"
    if strict_quality and not delivery_quality_frozen:
        disposition, owner = "delivery_quality_planning_required", "quality_planning"
    state["question_history"] = update_quality_question_states(
        state["question_history"],
        turn_index=state["turn_index"],
        supplied_inputs=dict(supplied_inputs or {}),
        utterance=command_text,
    )
    for question in state["question_history"]:
        if question.get("status") != "open":
            continue
        if (
            str(question.get("intent", "")).startswith("supply:")
            and str(question["intent"]).split(":", 1)[1] in state["active_inputs"]
        ):
            question["status"] = "resolved"
            question["resolved_turn_index"] = state["turn_index"]
        elif (
            question.get("intent") == "distinguish:desired_outcome"
            and adjudication.get("status") == "selected"
        ):
            question["status"] = "resolved"
            question["resolved_turn_index"] = state["turn_index"]
    elicitation = build_elicitation(binding, adjudication, state)
    state["question_history"].extend(elicitation["questions"])
    quality_question_open = any(
        str(row.get("intent", "")).startswith("quality:")
        and row.get("status") in {"open", "non_answer", "conflicting"}
        and row.get("blocking")
        for row in state["question_history"]
    )
    if quality_question_open and not strict_quality:
        disposition, owner = "clarification_required", "understanding"
    state["open_decisions"] = [
        {
            "kind": "missing_input",
            "field": field,
            "source_turn_index": state["turn_index"],
        }
        for field in binding.get("material_missing", ())
    ]
    alternatives = list(adjudication.get("serious_alternatives", ()))
    handoff = None
    quality_handoff = {
        "schema_version": "lunar.planner.contextual-quality-handoff/v1",
        "outcome_contract_digest": outcome_quality_contract["digest"],
        "delivery_plan_digest": delivery_quality_plan["digest"],
        "must_pass_criterion_ids": [
            row["criterion_id"]
            for row in delivery_quality_plan["criteria"]
            if row["severity"] == "must_pass"
        ],
        "evidence_whitelist": list(delivery_quality_plan["evidence_whitelist"]),
        "risk_tier": delivery_quality_plan["risk_tier"],
        "assessment_required": delivery_quality_frozen,
        "independent_quality_validation_required": not delivery_quality_frozen,
        "release_authorized": False,
        "route_only": True,
    }
    quality_handoff["digest"] = _digest(quality_handoff)
    if disposition == "ready_for_delivery":
        handoff = {
            "schema_version": HANDOFF_SCHEMA,
            "selected_target": adjudication["selected"],
            "bindings": binding["ports"],
            "adapter_mode": (
                "compile_only"
                if adjudication["selected"]["kind"] == "planning_subworkflow"
                else "instruction_only_advisory"
            ),
            "route_locked": True,
            "planner_execution": False,
        }
        handoff["digest"] = _digest(handoff)
    public_retrieval = {
        **retrieval,
        "candidates": [
            {key: value for key, value in row.items() if key != "contract"}
            for row in retrieval["candidates"]
        ],
    }
    state["current_stage_digest"] = _digest(
        {
            "request_frame": frame,
            "retrieval": public_retrieval,
            "adjudication": adjudication,
            "requirement_ledger": requirement_ledger,
            "workflow_draft": workflow_draft,
            "workflow_instantiation": workflow_instantiation,
            "proposed_skill_test_plans": proposed_skill_test_plans,
            **(
                {"post_plan_evidence_verification": post_plan_evidence_verification}
                if post_plan_evidence_verification is not None
                else {}
            ),
            **(
                {"answer_control_readiness": answer_control_readiness}
                if answer_control_readiness is not None
                else {}
            ),
            **(
                {"answer_control_readiness_card": answer_control_readiness_card}
                if answer_control_readiness_card is not None
                else {}
            ),
            **(
                {
                    "workflow_workload_inventory": workflow_workload_inventory,
                    "workflow_effort_estimate": workflow_effort_estimate,
                    "workflow_resource_estimate": workflow_resource_estimate,
                    "workflow_effort_card": workflow_effort_card,
                    "workflow_economics_report": workflow_economics_report,
                }
                if workflow_economics_report is not None
                else {}
            ),
            "workflow_refinement_cycle": workflow_refinement_cycle,
            "capability_gap_plan": capability_gap_plan,
            "outcome_quality_contract": outcome_quality_contract,
            "delivery_quality_plan": delivery_quality_plan,
        }
    )
    state["digest"] = _state_digest(state)
    if strict_quality and not delivery_quality_frozen:
        continuation_value = _quality_checkpoint_continuation(
            frame,
            snapshot_digest,
            state,
            phase="delivery_quality_planning_required",
            outcome_contract=outcome_quality_contract,
            delivery_plan=delivery_quality_plan,
        )
    else:
        continuation_value = _continuation(
            frame,
            snapshot_digest,
            binding.get("material_missing", []),
            alternatives,
            adjudication.get("selected"),
            state,
            elicitation,
        )
    receipt = {
        "schema_version": RECEIPT_SCHEMA,
        "request_frame": frame,
        "catalog_snapshot": {
            "schema_version": surface.get("schema_version"),
            "digest": snapshot_digest,
            "test_snapshot": test_snapshot,
        },
        "retrieval": public_retrieval,
        "adjudication": adjudication,
        "decomposition": decomposition,
        "dialogue_state": state,
        "requirement_ledger": requirement_ledger,
        "workflow_draft": workflow_draft,
        "workflow_instantiation": workflow_instantiation,
        "proposed_skill_test_plans": proposed_skill_test_plans,
        **(
            {"post_plan_evidence_verification": post_plan_evidence_verification}
            if post_plan_evidence_verification is not None
            else {}
        ),
        **(
            {"answer_control_readiness": answer_control_readiness}
            if answer_control_readiness is not None
            else {}
        ),
        **(
            {"answer_control_readiness_card": answer_control_readiness_card}
            if answer_control_readiness_card is not None
            else {}
        ),
        **(
            {
                "workflow_workload_inventory": workflow_workload_inventory,
                "workflow_effort_estimate": workflow_effort_estimate,
                "workflow_resource_estimate": workflow_resource_estimate,
                "workflow_effort_card": workflow_effort_card,
                "workflow_economics_report": workflow_economics_report,
            }
            if workflow_economics_report is not None
            else {}
        ),
        "workflow_refinement_cycle": workflow_refinement_cycle,
        "selected_targets": selected_targets,
        "binding": binding,
        "preflight": preflight_result,
        "disposition": disposition,
        "primary_failure_owner": owner if disposition != "ready_for_delivery" else None,
        "continuation": continuation_value,
        "elicitation": elicitation,
        "delivery_handoff": handoff,
        "capability_gap_plan": capability_gap_plan,
        "outcome_quality_contract": outcome_quality_contract,
        "outcome_quality_review": outcome_quality_review,
        "delivery_quality_plan": delivery_quality_plan,
        "delivery_quality_review": delivery_quality_review,
        "quality_handoff": quality_handoff,
        "quality_disposition": (
            "artifact_assessment_required"
            if disposition == "ready_for_delivery" and delivery_quality_frozen
            else (
                disposition
                if disposition
                in {"quality_planning_required", "delivery_quality_planning_required"}
                else (
                    "quality_validation_required"
                    if disposition == "ready_for_delivery"
                    else "not_deliverable"
                )
            )
        ),
        "route_only": True,
    }
    if (
        verification_context
        and verification_context.get("package_search_receipt") is not None
    ):
        receipt["package_search_receipt"] = verification_context[
            "package_search_receipt"
        ]
    selected_names = [str(row.get("name") or row.get("id")) for row in selected_targets]
    alternative_names = [
        str(row.get("name") or row.get("id")) if isinstance(row, Mapping) else str(row)
        for row in alternatives[:5]
    ]
    workflow_blockers = [
        str(
            row.get("edge_id")
            or ",".join(row.get("requirement_ids", ()))
            or row.get("status")
        )
        for row in workflow_instantiation.get("blockers", ())
    ]
    reasoning_status = (
        "blocked"
        if disposition
        in {"blocked", "blocked_for_refinement", "clarification_required"}
        else "planned"
    )
    reasoning_log = build_reasoning_log(
        subject_kind="planner",
        subject_id=f"{state['dialogue_id']}:turn-{state['turn_index']}",
        summary=(
            f"Lunar framed {len(decomposition)} active obligation(s), selected "
            f"{len(selected_targets)} reusable target(s), and ended in {disposition}."
        ),
        status=reasoning_status,
        events=[
            {
                "stage": "intent and requirement framing",
                "actor": {"kind": "planner", "id": "lunar-planner"},
                "action": "Reduced the current dialogue into active, corrected, and withdrawn obligations.",
                "rationale_summary": "Only user-supplied turns and typed inputs were admitted; revisions remain auditable.",
                "inputs_used": [
                    f"dialogue turn {state['turn_index']}",
                    *sorted(state.get("active_inputs", {}).keys()),
                ],
                "decision": {
                    "status": "accepted",
                    "outcome": f"{len(decomposition)} active obligation(s) are represented.",
                    "alternatives_considered": [],
                },
                "outputs": ["request frame", "requirement ledger"],
                "checks": [
                    "dialogue lineage retained",
                    "typed supplied inputs remain authoritative",
                ],
            },
            {
                "stage": "reuse discovery and adjudication",
                "actor": {"kind": "planner", "id": "lunar-planner"},
                "action": "Searched the sealed capability surface and adjudicated semantic fit.",
                "rationale_summary": "Candidate scores nominate possibilities; selected targets still require complete instruction and contract review.",
                "inputs_used": ["normalized obligations", "sealed catalog snapshot"],
                "decision": {
                    "status": "selected" if selected_names else "deferred",
                    "outcome": (
                        "; ".join(selected_names)
                        if selected_names
                        else "No reusable target was selected."
                    ),
                    "alternatives_considered": alternative_names,
                },
                "outputs": ["candidate receipt", "semantic adjudication"],
                "checks": [
                    "reuse evaluated before gap authoring",
                    "availability and authority remain explicit",
                ],
            },
            *(
                [
                    {
                        "stage": "post-plan evidence and determinism verification",
                        "actor": {
                            "kind": "planner",
                            "id": "post-plan-evidence-grounding-verifier",
                        },
                        "action": str(
                            post_plan_evidence_verification["summary_event"]["action"]
                        ),
                        "rationale_summary": str(
                            post_plan_evidence_verification["summary_event"][
                                "rationale_summary"
                            ]
                        ),
                        "inputs_used": [
                            "immutable workflow instantiation",
                            "requirement ledger",
                            "already-produced planning receipts",
                        ],
                        "decision": {
                            "status": (
                                "blocked"
                                if post_plan_evidence_verification["status"]
                                == "repair_required"
                                else "accepted"
                            ),
                            "outcome": str(post_plan_evidence_verification["status"]),
                            "alternatives_considered": [],
                        },
                        "outputs": ["post-plan evidence verification sidecar"],
                        "checks": list(
                            post_plan_evidence_verification["summary_event"]["checked"]
                        ),
                        "blockers": [
                            str(row.get("target"))
                            for row in post_plan_evidence_verification.get(
                                "findings", ()
                            )
                            if row.get("severity") == "block"
                        ],
                    }
                ]
                if post_plan_evidence_verification is not None
                else []
            ),
            *(
                [
                    {
                        "stage": "answer control readiness",
                        "actor": {"kind": "planner", "id": "answer-control-readiness"},
                        "action": "Compiled the controls and observed receipts required to assess a future exact answer.",
                        "rationale_summary": "This prospective sidecar reports an attainable control band and never treats planned controls as executed evidence or a realized trust score.",
                        "inputs_used": [
                            "immutable workflow instantiation",
                            "post-plan evidence verification sidecar",
                            "versioned answer trust policy",
                        ],
                        "decision": {
                            "status": "planned",
                            "outcome": str(
                                answer_control_readiness["attainable_control_band"]
                            ),
                            "alternatives_considered": [],
                        },
                        "outputs": ["score-free answer control readiness sidecar"],
                        "checks": [
                            "real evidence obligations are explicit",
                            "generative preservation controls are explicit",
                            "realized trust score is absent",
                            "initial plan digest is unchanged",
                        ],
                        "blockers": [
                            str(row.get("finding_id"))
                            for row in answer_control_readiness.get("findings", ())
                            if row.get("severity") == "high"
                        ],
                    }
                ]
                if answer_control_readiness is not None
                else []
            ),
            {
                "stage": "workflow instantiation and refinement",
                "actor": {"kind": "planner", "id": "lunar-planner"},
                "action": "Mapped requirements to reusable components, governed gaps, delivery contracts, and typed handoffs.",
                "rationale_summary": "The route remains planning-only and release is blocked until declared execution checks pass.",
                "inputs_used": [
                    "requirement ledger",
                    "component contracts",
                    "authority envelope",
                ],
                "decision": {
                    "status": "blocked" if workflow_blockers else "accepted",
                    "outcome": workflow_refinement_cycle.get("status", disposition),
                    "alternatives_considered": [],
                },
                "outputs": [
                    "workflow instantiation",
                    "proposed skill tests",
                    "refinement cycle",
                ],
                "checks": list(workflow_refinement_cycle.get("required_test_ids", ()))[
                    :20
                ],
                "blockers": workflow_blockers,
            },
        ],
        assumptions=state.get("assumptions", ()),
        evidence_references=[
            {
                "id": "catalog-snapshot",
                "kind": "catalog_snapshot",
                "locator": "planner catalog snapshot",
                "description": "Sealed capability surface used for this planning turn.",
                "digest": snapshot_digest,
            }
        ],
        blockers=workflow_blockers,
        limitations=[
            "This is a decision trace, not hidden chain-of-thought.",
            "Planning and selection do not demonstrate that any skill or workflow executed.",
            "Candidate ranking is not semantic validation of full skill instructions.",
        ],
    )
    receipt["reasoning_log"] = reasoning_log
    receipt["reasoning_log_markdown"] = render_reasoning_log_markdown(reasoning_log)
    receipt["digest"] = _digest(receipt)
    return receipt
