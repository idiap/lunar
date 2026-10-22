# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0

"""Consequence-based quality policy, elicitation, and criterion lifecycle.

Purpose: provide the `quality governance` implementation within `Lunar planner`. Key concepts: explicit responsibility, typed interfaces, and reproducible behavior. Principal I/O and failure semantics are defined by the public callables below.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

from .contracts import canonical_digest, seal_quality_contract

RISK_POLICIES: dict[str, dict[str, Any]] = {
    "control": {
        "evaluator_modes": ["deterministic"],
        "independent_semantic_review": False,
        "repeats": 0,
        "human_gate": False,
        "timeout_seconds": 0,
        "cost_ceiling_units": 0,
        "fallback": "return deterministic control result",
    },
    "ordinary": {
        "evaluator_modes": ["deterministic", "generative"],
        "independent_semantic_review": True,
        "repeats": 1,
        "human_gate": False,
        "timeout_seconds": 30,
        "cost_ceiling_units": 1,
        "fallback": "inconclusive",
    },
    "complex": {
        "evaluator_modes": ["deterministic", "generative", "composition"],
        "independent_semantic_review": True,
        "repeats": 2,
        "human_gate": False,
        "timeout_seconds": 90,
        "cost_ceiling_units": 3,
        "fallback": "inconclusive_or_human_adjudication",
    },
    "human_authority": {
        "evaluator_modes": ["deterministic", "generative", "human"],
        "independent_semantic_review": True,
        "repeats": 2,
        "human_gate": True,
        "timeout_seconds": 90,
        "cost_ceiling_units": 3,
        "fallback": "blocked_pending_human_authority",
    },
}


def normalize_consequence_profile(
    request: str, *, explicit_profile: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """Extract explicit decision consequences without classifying by topic.

    A treatment word is insufficient.  Human-authority consequence requires an
    explicit patient scope, an action to choose/recommend/prescribe/decide, and
    a clinical intervention object.  Evidence-discussion requests therefore
    stay semantic while actual patient decisions are human gated.
    """

    profile = dict(explicit_profile or {})
    lowered = request.casefold()
    patient_scope = bool(
        re.search(
            r"\b(?:this|the) patient\b|\bpatient[- ]level\b|\bindividual patient\b",
            lowered,
        )
    )
    decision_action = bool(
        re.search(
            r"\b(?:make|recommend|select|choose|prescribe|decide|exclude)\b", lowered
        )
    )
    intervention = bool(
        re.search(
            r"\b(?:\w*therap(?:y|ies)|treatment|regimen|drug|dose|surgery|"
            r"clinical management)\b",
            lowered,
        )
    )
    clinical_decision = patient_scope and decision_action and intervention
    if clinical_decision:
        profile.update(
            clinical_decision=True,
            human_authority_required=True,
            decision_scope="patient_level",
            consequence_evidence=[
                "explicit patient scope",
                "explicit clinical decision action",
                "explicit intervention object",
            ],
        )
    regulatory_action = bool(
        re.search(r"\b(?:submit|file|approve|authorize|certify)\b", lowered)
        and re.search(
            r"\b(?:regulator|regulatory submission|marketing authorization|health authority)\b",
            lowered,
        )
    )
    if regulatory_action:
        profile.update(
            regulatory_decision=True,
            human_authority_required=True,
            decision_scope="regulatory",
            consequence_evidence=[
                "explicit regulatory action",
                "explicit regulatory decision object or authority",
            ],
        )
    return profile


def classify_quality_policy(frame: Mapping[str, Any]) -> dict[str, Any]:
    """Tier a request from declared consequences, composition, and authority.

    Topic words are intentionally ignored. Callers must make consequences
    explicit in the normalized frame or authority envelope.
    """

    consequence = dict(frame.get("consequence_profile", {}))
    authority = dict(frame.get("authority", frame.get("authority_envelope", {})))
    request_class = str(frame.get("request_class", ""))
    human_required = bool(
        consequence.get("human_authority_required")
        or consequence.get("clinical_decision")
        or consequence.get("regulatory_decision")
        or consequence.get("irreversible_external_action")
        or authority.get("human_gate_required")
        or authority.get("decision_authority") in {"clinical", "regulatory", "legal"}
    )
    composed = bool(
        consequence.get("multi_stage")
        or consequence.get("composition_required")
        or int(consequence.get("handoff_count", 0) or 0) > 0
        or frame.get("persistent_change_requested")
        or len(frame.get("intent_units", ())) > 1
    )
    control = bool(
        frame.get("control_route")
        or request_class
        in {"greeting", "capability_help", "catalog_metadata", "control"}
    )
    tier = (
        "human_authority"
        if human_required
        else ("complex" if composed else ("control" if control else "ordinary"))
    )
    return {
        "tier": tier,
        "basis": {
            "human_authority_required": human_required,
            "composition_required": composed,
            "control_route": control,
            "declared_consequences": consequence,
            "declared_authority": authority,
        },
        **RISK_POLICIES[tier],
    }


def material_quality_elicitation(
    frame: Mapping[str, Any], state: Mapping[str, Any]
) -> dict[str, Any] | None:
    """Return one consequential outcome question, or an existing open state."""

    goal = str(frame.get("goal", state.get("active_goal", "")))
    lowered = goal.casefold()
    active_inputs = dict(state.get("active_inputs", {}))
    history = [dict(row) for row in state.get("question_history", ())]
    unresolved = next(
        (
            row
            for row in reversed(history)
            if str(row.get("intent", "")).startswith("quality:")
            and row.get("status") in {"open", "non_answer", "conflicting"}
        ),
        None,
    )
    if unresolved:
        return {
            "intent": str(unresolved["intent"]),
            "status": "already_open",
            "question_id": unresolved.get("question_id"),
            "missing_fields": list(unresolved.get("missing_fields", ())),
            "blocking": True,
        }
    explicit_audience = active_inputs.get("audience") or re.search(
        r"\b(?:tumou?r board|patient advocate|regulator|regulatory reviewer|specialist|clinician|public audience|internal research team)\b",
        lowered,
    )
    explicit_use = active_inputs.get("intended_use") or active_inputs.get(
        "supported_decision"
    )
    share_judgment = bool(
        re.search(r"\bgood enough\b.*\bshare|\bready\b.*\bshare|\bshareable\b", lowered)
    )
    convincing = bool(re.search(r"\b(?:more )?convincing\b", lowered))
    if convincing:
        intent = "quality:intended_decision_or_weakness"
        prompt = "Which reader decision or identified weakness should this revision address, without strengthening claims beyond the evidence?"
        missing_fields = ["intended_use", "identified_weakness"]
    elif share_judgment and not (explicit_audience and explicit_use):
        intent = "quality:audience_and_intended_use"
        prompt = "Who is the intended audience, and what decision or use must the report safely support?"
        missing_fields = [
            name
            for name, value in (
                ("audience", explicit_audience),
                ("intended_use", explicit_use),
            )
            if not value
        ]
    else:
        return None
    return {
        "intent": intent,
        "status": "ask",
        "prompt": prompt,
        "expected_decision_effect": "the answer changes must-pass audience, evidence-ceiling, and release criteria",
        "missing_fields": missing_fields,
        "blocking": True,
    }


def update_quality_question_states(
    history: Iterable[Mapping[str, Any]],
    *,
    turn_index: int,
    supplied_inputs: Mapping[str, Any],
    utterance: str,
) -> list[dict[str, Any]]:
    """Resolve or retain quality questions without repeating non-answers."""

    result = [dict(row) for row in history]
    non_answer = bool(
        re.search(
            r"\b(?:do not know|don't know|unsure|not decided|cannot answer)\b",
            utterance,
            re.IGNORECASE,
        )
    )
    conflicting = any(
        isinstance(value, Mapping) and value.get("_conflict")
        for value in supplied_inputs.values()
    )
    for row in result:
        if row.get("status") not in {"open", "non_answer", "conflicting"} or not str(
            row.get("intent", "")
        ).startswith("quality:"):
            continue
        required = set(map(str, row.get("missing_fields", ())))
        if conflicting:
            row["status"] = "conflicting"
            row["last_response_turn_index"] = turn_index
        elif non_answer:
            row["status"] = "non_answer"
            row["last_response_turn_index"] = turn_index
        elif required and required <= set(supplied_inputs):
            row["status"] = "resolved"
            row["resolved_turn_index"] = turn_index
    return result


_HARD_BOUNDARY_TERMS = {
    "provenance",
    "authority",
    "privacy",
    "deterministic integrity",
    "claim ceiling",
}


def criterion_transition_errors(
    previous: Mapping[str, Any],
    revised: Mapping[str, Any],
    *,
    actor_kind: str,
    trigger: str,
) -> tuple[str, ...]:
    """Reject planner/judge weakening and post-failure criterion relaxation."""

    errors: list[str] = []
    if previous.get("criterion_id") != revised.get("criterion_id"):
        errors.append("criterion identity cannot change in place")
    if (
        previous.get("severity") == "must_pass"
        and revised.get("severity") != "must_pass"
        and actor_kind not in {"user", "governing_contract"}
    ):
        errors.append("planner or evaluator cannot downgrade a must-pass criterion")
    if (
        previous.get("separation_required")
        and not revised.get("separation_required")
        and actor_kind not in {"user", "governing_contract"}
    ):
        errors.append(
            "planner or evaluator cannot remove producer/evaluator separation"
        )
    old_prohibited = set(map(str, previous.get("prohibited_outcomes", ())))
    new_prohibited = set(map(str, revised.get("prohibited_outcomes", ())))
    if not old_prohibited <= new_prohibited and actor_kind not in {
        "user",
        "governing_contract",
    }:
        errors.append("planner or evaluator cannot remove prohibited outcomes")
    if trigger == "failed_assessment" and any(
        previous.get(key) != revised.get(key)
        for key in (
            "severity",
            "pass_condition",
            "authority_ceiling",
            "prohibited_outcomes",
            "evaluator_mode",
        )
    ):
        errors.append("a failed assessment cannot relax or rewrite its criterion")
    return tuple(errors)


def revise_quality_contract(
    contract: Mapping[str, Any],
    changes: Iterable[Mapping[str, Any]],
    *,
    next_version: int,
    actor_kind: str,
    parent_digest: str,
) -> dict[str, Any]:
    """Create an auditable selective-invalidation receipt for criterion changes."""

    if parent_digest != contract.get("digest") or canonical_digest(
        contract
    ) != contract.get("digest"):
        return {
            "status": "rejected",
            "reason": "stale_or_tampered_parent",
            "revised_contract": None,
        }
    change_rows = [dict(row) for row in changes]
    material = [
        row for row in change_rows if row.get("old_digest") != row.get("new_digest")
    ]
    if not material:
        return {
            "status": "no_op",
            "reason": "no dependency value changed",
            "revised_contract": dict(contract),
        }
    dependencies = {str(row.get("dependency")) for row in material}
    criteria: list[dict[str, Any]] = []
    invalidated: list[str] = []
    rejected: list[str] = []
    for source in contract.get("criteria", ()):
        row = dict(source)
        criterion_dependencies = set(map(str, row.get("invalidation_inputs", ())))
        affected = bool(dependencies & criterion_dependencies)
        withdrawal = next(
            (
                item
                for item in material
                if item.get("action") == "withdraw"
                and (
                    not item.get("criterion_id")
                    or item.get("criterion_id") == row.get("criterion_id")
                )
            ),
            None,
        )
        hard_boundary = bool(
            _HARD_BOUNDARY_TERMS & {item.casefold() for item in criterion_dependencies}
        )
        if withdrawal and (
            actor_kind not in {"user", "governing_contract"} or hard_boundary
        ):
            rejected.append(str(row.get("criterion_id")))
        elif withdrawal:
            row["lifecycle"] = "withdrawn"
            row["withdrawn_in_version"] = next_version
            invalidated.append(str(row.get("criterion_id")))
        elif affected:
            row["lifecycle"] = "superseded"
            invalidated.append(str(row.get("criterion_id")))
        criteria.append(row)
    if rejected:
        return {
            "status": "rejected",
            "reason": "withdrawal lacks authority or targets a mandatory framework boundary",
            "rejected_criterion_ids": rejected,
            "revised_contract": None,
        }
    revised = dict(contract)
    revised.update(
        version=next_version,
        lifecycle="provisional",
        review_status="pending",
        parent_digest=contract.get("digest"),
        criteria=criteria,
        invalidated_by=sorted(dependencies),
        change_lineage=[
            {
                "dependency": row.get("dependency"),
                "action": row.get("action", "revise"),
                "source_turn_id": row.get("source_turn_id"),
                "actor_kind": actor_kind,
            }
            for row in material
        ],
    )
    revised = seal_quality_contract(revised)
    return {
        "status": "revised",
        "invalidated_criterion_ids": invalidated,
        "preserved_criterion_ids": [
            str(row.get("criterion_id"))
            for row in criteria
            if row.get("criterion_id") not in invalidated
        ],
        "assessment_reuse_allowed": False,
        "revised_contract": revised,
    }
