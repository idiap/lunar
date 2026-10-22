# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0

"""Deterministic answer-grounding and generative-masking assessment.

This module is deliberately pure.  It neither retrieves evidence nor executes a
workflow: it projects already authenticated planner records into a prospective
readiness sidecar or a retrospective assessment bound to an exact answer.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any

READINESS_SCHEMA = "lunar.planner.answer-control-readiness/v1"
ASSESSMENT_SCHEMA = "lunar.planner.answer-trust-assessment/v1"
INVALIDATION_SCHEMA = "lunar.planner.answer-trust-invalidation/v1"
TRUST_CARD_SCHEMA = "lunar.planner.answer-trust-card/v1"
ROLLOUT_STATES = ("off", "fixture", "shadow", "audit", "advisory", "enforcement")

DEFAULT_POLICY: dict[str, Any] = {
    "policy_version": "1.0.0",
    "policy_digest": "sha256:7556170c0cfa1d9516454540ad84913274d951c74fc343f575bed26caa276d4d",
    "weights": {
        "external_grounding": 0.30,
        "lineage_closure": 0.20,
        "preservation_fidelity": 0.20,
        "authority_directness_applicability": 0.15,
        "generative_containment": 0.10,
        "uncertainty_conflict_control": 0.05,
    },
    "epsilon": 1e-12,
    "interval_width_limit": 20.0,
    "critical_claim_threshold": 70.0,
    "bands": (
        (85.0, "high_control"),
        (70.0, "substantiated"),
        (50.0, "guarded"),
        (25.0, "low"),
        (0.0, "blocked_untrusted"),
    ),
    "rollout": {
        "states": ROLLOUT_STATES,
        "default_state": "off",
        "pinned_rollback_state": "off",
        "readiness_enabled_states": ROLLOUT_STATES[1:],
        "assessment_enabled_states": ROLLOUT_STATES[1:],
        "user_visible_states": ("advisory", "enforcement"),
        "release_effect_states": ("enforcement",),
    },
    "promotion_gates": {
        "fabricated_value_detection_rate": 1.0,
        "citation_lineage_mismatch_detection_rate": 1.0,
        "planned_as_observed_escape_count": 0,
        "score_replay_mismatch_count": 0,
        "legacy_compatibility_failure_count": 0,
        "maximum_false_block_rate": 0.05,
        "maximum_p95_latency_ms": 250,
        "maximum_mean_artifact_bytes": 500000,
        "minimum_human_review_capacity": 2,
    },
}

_EXEMPT_CLASSES = {
    "explicit_unknown",
    "user_preference",
    "user_constraint",
    "prospective_action",
    "method_description",
}
_REAL_EVIDENCE_ORIGINS = {"external", "observed", "primary_data", "run_artifact"}
_PROHIBITED_EVIDENCE_ORIGINS = {
    "model_memory",
    "generated",
    "retrieval_hint",
    "planned",
}


class AnswerTrustError(ValueError):
    """Raised when an assessment input violates a trust invariant."""


def _canonical(value: Any) -> str:
    """Canonical."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _digest(value: Any) -> str:
    """Digest."""
    return "sha256:" + hashlib.sha256(_canonical(value).encode()).hexdigest()


def _seal(value: Mapping[str, Any]) -> dict[str, Any]:
    """Seal."""
    result = deepcopy(dict(value))
    result.pop("digest", None)
    result["digest"] = _digest(result)
    return result


def _policy(value: Mapping[str, Any] | None) -> dict[str, Any]:
    """Policy."""
    result = deepcopy(DEFAULT_POLICY)
    if value:
        result.pop("policy_digest", None)
        for key, item in value.items():
            if key == "weights":
                result[key].update(item)
            elif key == "dimension_weights":
                result["weights"].update(item)
            elif key == "digest":
                result["policy_digest"] = item
            elif key == "answer_aggregation" and isinstance(item, Mapping):
                if "maximum_crisp_interval_width" in item:
                    result["interval_width_limit"] = item[
                        "maximum_crisp_interval_width"
                    ]
                if "critical_claim_high_control_floor" in item:
                    result["critical_claim_threshold"] = item[
                        "critical_claim_high_control_floor"
                    ]
            elif key == "tiers" and isinstance(item, Sequence):
                result["bands"] = tuple(
                    (float(row["minimum"]), str(row["label"]))
                    for row in item
                    if isinstance(row, Mapping)
                )
            else:
                result[key] = deepcopy(item)
    weights = result["weights"]
    if set(weights) != set(DEFAULT_POLICY["weights"]):
        raise AnswerTrustError(
            "policy weights must define exactly the six v1 dimensions"
        )
    if any(not 0 <= float(weight) <= 1 for weight in weights.values()):
        raise AnswerTrustError("dimension weights must be in [0, 1]")
    if not math.isclose(sum(float(value) for value in weights.values()), 1.0):
        raise AnswerTrustError("dimension weights must sum to 1")
    return result


def _policy_digest(policy: Mapping[str, Any]) -> str:
    """Policy digest."""
    return str(policy.get("policy_digest") or _digest(policy))


def _band(score: float, policy: Mapping[str, Any]) -> str:
    """Band."""
    for threshold, label in policy["bands"]:
        if score >= float(threshold):
            return str(label)
    return "blocked_untrusted"


def resolve_answer_trust_rollout(
    state: str = "off",
    *,
    promotion_metrics: Mapping[str, float | int] | None = None,
    policy: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve one rollout state without granting implicit release authority."""

    score_policy = _policy(policy)
    rollout = score_policy.get("rollout", DEFAULT_POLICY["rollout"])
    states = tuple(map(str, rollout.get("states", ROLLOUT_STATES)))
    selected = str(state)
    if selected not in states:
        raise AnswerTrustError(f"unsupported answer trust rollout state: {selected}")
    gates = score_policy.get("promotion_gates", DEFAULT_POLICY["promotion_gates"])
    blockers: list[str] = []
    metrics = dict(promotion_metrics or {})
    if selected == "enforcement":
        minimums = {
            "fabricated_value_detection_rate": float(
                gates["fabricated_value_detection_rate"]
            ),
            "citation_lineage_mismatch_detection_rate": float(
                gates["citation_lineage_mismatch_detection_rate"]
            ),
            "minimum_human_review_capacity": float(
                gates["minimum_human_review_capacity"]
            ),
        }
        maximums = {
            "planned_as_observed_escape_count": float(
                gates["planned_as_observed_escape_count"]
            ),
            "score_replay_mismatch_count": float(gates["score_replay_mismatch_count"]),
            "legacy_compatibility_failure_count": float(
                gates["legacy_compatibility_failure_count"]
            ),
            "false_block_rate": float(gates["maximum_false_block_rate"]),
            "p95_latency_ms": float(gates["maximum_p95_latency_ms"]),
            "mean_artifact_bytes": float(gates["maximum_mean_artifact_bytes"]),
        }
        for key, minimum in minimums.items():
            if key not in metrics or float(metrics[key]) < minimum:
                blockers.append(
                    f"{key} is below the enforcement promotion minimum {minimum}"
                )
        for key, maximum in maximums.items():
            if key not in metrics or float(metrics[key]) > maximum:
                blockers.append(
                    f"{key} exceeds the enforcement promotion maximum {maximum}"
                )
    release_effect = (
        selected in set(map(str, rollout.get("release_effect_states", ())))
        and not blockers
    )
    return _seal(
        {
            "schema_version": "lunar.planner.answer-trust-rollout/v1",
            "requested_state": selected,
            "effective_state": selected if not blockers else "advisory",
            "readiness_enabled": selected
            in set(map(str, rollout.get("readiness_enabled_states", ()))),
            "assessment_enabled": selected
            in set(map(str, rollout.get("assessment_enabled_states", ()))),
            "user_visible": selected
            in set(map(str, rollout.get("user_visible_states", ()))),
            "release_effect_enabled": release_effect,
            "promotion_authorized": selected != "enforcement" or not blockers,
            "promotion_blockers": blockers,
            "pinned_rollback_state": str(rollout.get("pinned_rollback_state", "off")),
            "policy_digest": _policy_digest(score_policy),
        }
    )


def _claim_exemption(claim: Mapping[str, Any]) -> str | None:
    """Claim exemption."""
    claim_class = str(claim.get("claim_class", "material_factual"))
    if claim.get("exempt") is True or claim_class in _EXEMPT_CLASSES:
        return str(claim.get("exemption_reason") or claim_class)
    return None


def build_answer_control_readiness(
    plan: Mapping[str, Any],
    verification: Mapping[str, Any],
    *,
    policy: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a score-free, prospective sidecar for a sealed initial plan."""

    score_policy = _policy(policy)
    claims = sorted(
        (
            dict(item)
            for item in verification.get("claim_atoms", verification.get("claims", ()))
        ),
        key=lambda item: str(item.get("claim_id", "")),
    )
    edges = sorted(
        (dict(item) for item in verification.get("derivation_edges", ())),
        key=lambda item: str(item.get("edge_id", "")),
    )
    envelopes = {
        str(item.get("claim_id")): dict(item)
        for item in verification.get("generative_envelopes", ())
        if item.get("claim_id")
    }
    obligations: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    severity_map = {
        "block": "critical",
        "critical": "critical",
        "repair": "high",
        "high": "high",
        "advisory": "medium",
        "medium": "medium",
        "low": "low",
    }
    for source_finding in verification.get("findings", ()):
        if not isinstance(source_finding, Mapping):
            continue
        source_id = str(source_finding.get("finding_id", "unknown"))
        owner = str(source_finding.get("owner", "evidence-grounding verifier"))
        findings.append(
            {
                "finding_id": f"readiness:{source_id}",
                "severity": severity_map.get(
                    str(source_finding.get("severity", "medium")), "medium"
                ),
                "plan_location": source_finding.get("target"),
                "message": str(
                    source_finding.get("message")
                    or "Existing evidence verification requires repair."
                ),
                "proposed_todo": {
                    "owner": owner,
                    "action": f"Resolve evidence-verification finding {source_id}",
                    "acceptance_evidence": "observed receipt satisfying the source verification obligation",
                },
            }
        )
    for claim in claims:
        claim_id = str(claim.get("claim_id", "unknown"))
        if _claim_exemption(claim):
            continue
        claim_class = str(
            claim.get("claim_class")
            or claim.get("assertion_kind")
            or "material_factual"
        )
        required = [
            "observed evidence identity",
            "content digest",
            "exact locator",
            "claim-to-component lineage",
        ]
        if claim_class in {"deterministic_derivation", "computed"}:
            required = [
                "grounded input lineage",
                "observed computation receipt",
                "recomputation check",
            ]
        if claim_class in {"hypothesis", "exploratory_hypothesis"}:
            required = [
                "hypothesis label",
                "grounded basis",
                "rival explanations",
                "discriminating test",
            ]
        if claim.get("release_critical") or claim.get("decision_risk") == "high":
            required.append("named independent or human review")
        for requirement in required:
            obligations.append(
                {
                    "claim_id": claim_id,
                    "receipt": requirement,
                    "status": "planned_unobserved",
                }
            )
    for edge in edges:
        operation = str(edge.get("kind") or edge.get("operation") or "").lower()
        if operation not in {"generative", "lossy", "semantic"} and not edge.get(
            "lossy"
        ):
            continue
        edge_id = str(edge.get("edge_id", "unknown"))
        present = set(edge.get("planned_controls", ()))
        output_claim = str(edge.get("output_claim_id") or edge.get("output_id") or "")
        envelope = envelopes.get(output_claim, {})
        if envelope.get("allowed_evidence_ids") is not None:
            present.add("allowed_evidence_envelope")
        if edge.get("preserved_qualifiers"):
            present.add("protected_field_checks")
        if envelope.get("independent_fidelity_verifier") and not envelope.get(
            "producer_may_self_approve", False
        ):
            present.add("independent_fidelity_review")
        required = {
            "allowed_evidence_envelope",
            "protected_field_checks",
            "independent_fidelity_review",
        }
        for missing in sorted(required - present):
            findings.append(
                {
                    "finding_id": f"readiness:{edge_id}:{missing}",
                    "severity": (
                        "high" if missing != "independent_fidelity_review" else "medium"
                    ),
                    "plan_location": edge.get("plan_location"),
                    "message": f"Generative or lossy edge lacks planned {missing.replace('_', ' ')}.",
                    "proposed_todo": {
                        "owner": str(edge.get("owner", "claim-fidelity-verifier")),
                        "action": f"Add {missing.replace('_', ' ')} for {edge_id}",
                        "acceptance_evidence": f"observed receipt proving {missing}",
                    },
                }
            )
    attainable = "undetermined" if not claims else "high_control"
    if any(item["severity"] == "critical" for item in findings):
        attainable = "blocked_untrusted"
    elif any(item["severity"] == "high" for item in findings):
        attainable = "guarded"
    elif findings:
        attainable = "substantiated"
    result = {
        "schema_version": READINESS_SCHEMA,
        "polarity": "prospective_only",
        "base_plan_digest": str(plan.get("digest") or _digest(plan)),
        "verification_digest": str(verification.get("digest") or _digest(verification)),
        "policy_version": score_policy["policy_version"],
        "policy_digest": _policy_digest(score_policy),
        "attainable_control_band": attainable,
        "realized_trust_score": None,
        "claims_considered": len(claims),
        "required_receipts": sorted(
            obligations, key=lambda item: (item["claim_id"], item["receipt"])
        ),
        "findings": sorted(findings, key=lambda item: item["finding_id"]),
        "mutates_initial_plan": False,
    }
    return _seal(result)


def _validate_realized_polarity(
    answer: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]
) -> str | None:
    """Validate realized polarity."""
    if not answer.get("digest"):
        return "exact answer digest is absent"
    if answer.get("execution_state", "observed") != "observed":
        return "answer is prospective rather than observed"
    if any(
        row.get("polarity") == "prospective_only" or row.get("observed") is False
        for row in rows
    ):
        return "prospective records were presented as realized inputs"
    return None


def _lineage_graph(
    edges: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, set[str]], set[str]]:
    """Lineage graph."""
    forward: dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        output = str(edge.get("output_id", ""))
        for input_id in edge.get("input_ids", ()):
            if output and input_id:
                forward[str(input_id)].add(output)
    visiting: set[str] = set()
    stack: list[str] = []
    visited: set[str] = set()
    cycles: set[str] = set()

    def visit(node: str) -> None:
        """Visit."""
        if node in visiting:
            start = stack.index(node)
            cycles.update(stack[start:])
            return
        if node in visited:
            return
        visiting.add(node)
        stack.append(node)
        for nxt in forward.get(node, ()):
            visit(nxt)
        stack.pop()
        visiting.remove(node)
        visited.add(node)

    for node in sorted(forward):
        visit(node)
    return forward, cycles


def _reachable(graph: Mapping[str, set[str]], start: str, targets: set[str]) -> bool:
    """Reachable."""
    pending = [start]
    seen: set[str] = set()
    while pending:
        node = pending.pop()
        if node in targets:
            return True
        if node in seen:
            continue
        seen.add(node)
        pending.extend(sorted(graph.get(node, ())))
    return False


def _mean(values: Sequence[float | None]) -> float | None:
    """Mean."""
    known = [float(value) for value in values if value is not None]
    return sum(known) / len(known) if known else None


def _bounded(value: Any) -> float | None:
    """Bounded."""
    if value is None:
        return None
    number = float(value)
    if not 0 <= number <= 1:
        raise AnswerTrustError(f"dimension grade outside [0, 1]: {number}")
    return number


def _evidence_projection(item: Mapping[str, Any]) -> dict[str, Any]:
    """Keep the joinable epistemic fields while avoiding source payload copies."""

    return {
        "evidence_id": str(item.get("evidence_id", "")),
        "origin": item.get("origin"),
        "authorized": item.get("authorized"),
        "content_digest": item.get("content_digest"),
        "locator": item.get("locator"),
        "observed_consumed": item.get("observed_consumed"),
        "independence_cluster": item.get("independence_cluster"),
        "generated_ancestor_ids": sorted(
            {str(value) for value in item.get("generated_ancestor_ids", ())}
        ),
    }


def _edge_projection(item: Mapping[str, Any]) -> dict[str, Any]:
    """Edge projection."""
    return {
        "edge_id": str(item.get("edge_id", "")),
        "input_ids": sorted(
            {str(value) for value in item.get("input_ids", item.get("inputs", ()))}
        ),
        "output_id": str(item.get("output_id") or item.get("output_claim_id") or ""),
        "kind": str(item.get("kind") or item.get("operation") or "unknown"),
        "observed": item.get("observed"),
        "receipt_id": item.get("receipt_id"),
    }


def _score_dimensions(
    dimensions: Mapping[str, float | None], policy: Mapping[str, Any], unknown: float
) -> float:
    """Score dimensions."""
    total = 0.0
    for name, weight in policy["weights"].items():
        value = dimensions.get(name)
        grade = unknown if value is None else float(value)
        total += float(weight) * math.log(max(grade, float(policy["epsilon"])))
    return 100.0 * math.exp(total)


def _claim_assessment(
    claim: Mapping[str, Any],
    evidence: Sequence[Mapping[str, Any]],
    edges: Sequence[Mapping[str, Any]],
    receipts: Mapping[str, Mapping[str, Any]],
    computation_receipts: Mapping[str, Mapping[str, Any]],
    graph: Mapping[str, set[str]],
    cycles: set[str],
    human_reviews: Sequence[Mapping[str, Any]],
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    """Claim assessment."""
    claim_id = str(claim.get("claim_id", ""))
    declared_components = {str(item) for item in claim.get("component_ids", ())}
    targets = declared_components | {claim_id}
    cited_ids = {str(item) for item in claim.get("evidence_ids", ())}
    supports = [item for item in evidence if str(item.get("evidence_id")) in cited_ids]
    valid = [
        item
        for item in supports
        if item.get("origin") in _REAL_EVIDENCE_ORIGINS
        and item.get("authorized", True)
        and item.get("observed_consumed", True)
        and not item.get("generated_ancestor_ids")
    ]
    gates: list[dict[str, Any]] = []
    caps: list[dict[str, Any]] = []
    repairs: list[str] = []
    paths = {
        str(item.get("evidence_id")): _reachable(
            graph, str(item.get("evidence_id")), targets
        )
        for item in supports
    }
    forbidden_only = bool(supports) and all(
        item.get("origin") in _PROHIBITED_EVIDENCE_ORIGINS for item in supports
    )
    if not supports and str(claim.get("claim_class", "material_factual")) not in {
        "hypothesis",
        "deterministic_derivation",
    }:
        gates.append(
            {
                "code": "missing_evidence",
                "consequence": "score_zero",
                "claim_id": claim_id,
            }
        )
        repairs.append(
            "Attach authorized observed evidence with an exact locator and consumed lineage path."
        )
    if forbidden_only:
        gates.append(
            {
                "code": "non_evidence_origin_only",
                "consequence": "score_zero",
                "claim_id": claim_id,
            }
        )
        repairs.append(
            "Replace model-memory, generated, planned, or retrieval-hint support with observed evidence."
        )
    for item in supports:
        evidence_id = str(item.get("evidence_id"))
        if (
            not item.get("authorized", True)
            or item.get("digest_mismatch")
            or item.get("fabricated")
        ):
            gates.append(
                {
                    "code": "invalid_evidence",
                    "consequence": "score_zero",
                    "claim_id": claim_id,
                    "evidence_id": evidence_id,
                }
            )
        if not paths[evidence_id]:
            gates.append(
                {
                    "code": "citation_without_lineage",
                    "consequence": "score_zero",
                    "claim_id": claim_id,
                    "evidence_id": evidence_id,
                }
            )
        if item.get("observed_consumed") is False:
            gates.append(
                {
                    "code": "evidence_not_observed_consumed",
                    "consequence": "score_zero",
                    "claim_id": claim_id,
                    "evidence_id": evidence_id,
                }
            )
        if item.get("origin") in _PROHIBITED_EVIDENCE_ORIGINS:
            gates.append(
                {
                    "code": "prohibited_material_used_as_evidence",
                    "consequence": "score_zero",
                    "claim_id": claim_id,
                    "evidence_id": evidence_id,
                }
            )
        if item.get("exact_mismatch"):
            gates.append(
                {
                    "code": "exact_source_mismatch",
                    "consequence": "score_zero",
                    "claim_id": claim_id,
                    "evidence_id": evidence_id,
                }
            )
        if item.get("origin") in _REAL_EVIDENCE_ORIGINS and item.get(
            "generated_ancestor_ids"
        ):
            gates.append(
                {
                    "code": "generated_evidence_recast",
                    "consequence": "score_zero",
                    "claim_id": claim_id,
                    "evidence_id": evidence_id,
                }
            )
        if not item.get("content_digest") or not item.get("locator"):
            caps.append(
                {
                    "code": "missing_digest_or_locator",
                    "maximum": 40.0,
                    "evidence_id": evidence_id,
                }
            )
    claim_edges = [
        item
        for item in edges
        if str(item.get("output_id")) in targets
        or claim_id in item.get("claim_ids", ())
    ]
    if cycles.intersection(targets | cited_ids):
        gates.append(
            {
                "code": "evidence_cycle",
                "consequence": "score_zero",
                "claim_id": claim_id,
            }
        )
    preservation_values: list[float | None] = []
    containment_values: list[float | None] = []
    generated_additions = 0
    preservation_failures = 0
    for edge in claim_edges:
        kind = str(edge.get("kind", "deterministic")).lower()
        if kind not in {"generative", "lossy", "semantic"}:
            computation = computation_receipts.get(str(edge.get("edge_id")))
            verification = edge.get("verified")
            if verification is None and computation is not None:
                verification = computation.get("recomputation_passed")
            preservation_values.append(
                None if verification is None else (1.0 if verification else 0.0)
            )
            containment_values.append(1.0)
            if verification is False:
                gates.append(
                    {
                        "code": "deterministic_verification_failed",
                        "consequence": "score_zero",
                        "claim_id": claim_id,
                        "edge_id": edge.get("edge_id"),
                    }
                )
            continue
        receipt = receipts.get(str(edge.get("edge_id")))
        if not receipt:
            preservation_values.append(None)
            containment_values.append(0.0)
            caps.append(
                {
                    "code": "missing_generative_receipt",
                    "maximum": 25.0,
                    "edge_id": edge.get("edge_id"),
                }
            )
            continue
        checks = [
            _bounded(value) for value in receipt.get("protected_fields", {}).values()
        ]
        preservation = _mean(checks)
        violations = list(receipt.get("violations", ()))
        if violations or any(value == 0 for value in checks):
            preservation_failures += 1
        if receipt.get("unsupported_additions"):
            generated_additions += 1
            preservation = 0.0
        preservation_values.append(preservation)
        contained = (
            bool(receipt.get("allowed_evidence_ids"))
            and bool(receipt.get("independent_verifier_id"))
            and not violations
        )
        containment_values.append(1.0 if contained else 0.0)
        if not contained:
            caps.append(
                {
                    "code": "uncontained_generative_edge",
                    "maximum": 25.0,
                    "edge_id": edge.get("edge_id"),
                }
            )
        if receipt.get("claim_ceiling_violation"):
            gates.append(
                {
                    "code": "claim_ceiling_violation",
                    "consequence": "score_zero",
                    "claim_id": claim_id,
                    "edge_id": edge.get("edge_id"),
                }
            )
    authority_grades = [
        _mean(
            [
                _bounded(item.get("authority")),
                _bounded(item.get("directness")),
                _bounded(item.get("applicability")),
            ]
        )
        for item in valid
    ]
    authority = max(
        (value for value in authority_grades if value is not None), default=None
    )
    uncertainty = _mean(
        [
            _bounded(claim.get("uncertainty_preserved")),
            _bounded(claim.get("conflicts_disclosed")),
            _bounded(claim.get("missingness_preserved")),
        ]
    )
    if claim.get("hidden_contradiction"):
        caps.append({"code": "hidden_or_unresolved_contradiction", "maximum": 50.0})
        uncertainty = 0.0
    requires_human = bool(claim.get("requires_human_review"))
    reviewed = any(
        review.get("claim_id") == claim_id and review.get("observed", True)
        for review in human_reviews
    )
    if requires_human and not reviewed:
        caps.append({"code": "missing_human_authority", "maximum": 60.0})
    dimensions: dict[str, float | None] = {
        "external_grounding": 1.0 if valid else 0.0,
        "lineage_closure": _mean(
            [1.0 if paths[str(item.get("evidence_id"))] else 0.0 for item in supports]
        ),
        "preservation_fidelity": (
            _mean(preservation_values)
            if claim_edges
            else _bounded(claim.get("preservation_fidelity", 1.0))
        ),
        "authority_directness_applicability": authority,
        "generative_containment": _mean(containment_values) if claim_edges else 1.0,
        "uncertainty_conflict_control": uncertainty,
    }
    fatal = bool(gates)
    lower = 0.0 if fatal else _score_dimensions(dimensions, policy, 0.0)
    upper = 0.0 if fatal else _score_dimensions(dimensions, policy, 1.0)
    cap = min([float(item["maximum"]) for item in caps], default=100.0)
    lower, upper = min(lower, cap), min(upper, cap)
    score = lower if math.isclose(lower, upper, abs_tol=1e-9) else None
    return {
        "claim_id": claim_id,
        "claim_class": str(claim.get("claim_class", "material_factual")),
        "component_ids": sorted(declared_components),
        "release_critical": bool(claim.get("release_critical")),
        "materiality_weight": float(claim.get("materiality_weight", 1.0)),
        "decision_risk_weight": float(claim.get("decision_risk_weight", 1.0)),
        "dimensions": dimensions,
        "score": score,
        "score_interval": [lower, upper],
        "gates": sorted(gates, key=_canonical),
        "caps": sorted(caps, key=_canonical),
        "evidence_ids": sorted(cited_ids),
        "grounded": bool(valid) and not fatal,
        "memory_only": forbidden_only,
        "citation_lineage_mismatch": any(not value for value in paths.values()),
        "unsupported_generative_additions": generated_additions,
        "preservation_failures": preservation_failures,
        "remediation": sorted(set(repairs)),
    }


def _weighted_harmonic(claims: Sequence[Mapping[str, Any]], bound_index: int) -> float:
    """Weighted harmonic."""
    weights = [
        float(item["materiality_weight"]) * float(item["decision_risk_weight"])
        for item in claims
    ]
    values = [float(item["score_interval"][bound_index]) for item in claims]
    if not values or any(value <= 0 for value in values):
        return 0.0
    return sum(weights) / sum(
        weight / value for weight, value in zip(weights, values, strict=True)
    )


def assess_answer_trust(
    answer: Mapping[str, Any],
    claims: Sequence[Mapping[str, Any]],
    evidence_atoms: Sequence[Mapping[str, Any]],
    derivation_edges: Sequence[Mapping[str, Any]],
    *,
    generative_receipts: Sequence[Mapping[str, Any]] = (),
    computation_receipts: Sequence[Mapping[str, Any]] = (),
    provenance_reconciliation: Mapping[str, Any] | None = None,
    quality_assessment: Mapping[str, Any] | None = None,
    human_reviews: Sequence[Mapping[str, Any]] = (),
    scoring_policy_digest: str | None = None,
    policy: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Assess one exact observed answer from retrospective evidence receipts."""

    score_policy = _policy(policy)
    actual_policy_digest = _policy_digest(score_policy)
    if scoring_policy_digest and scoring_policy_digest != actual_policy_digest:
        raise AnswerTrustError(
            "scoring policy digest does not match the supplied policy"
        )
    sorted_claims = sorted(
        (dict(item) for item in claims), key=lambda item: str(item.get("claim_id", ""))
    )
    sorted_evidence = sorted(
        (dict(item) for item in evidence_atoms),
        key=lambda item: str(item.get("evidence_id", "")),
    )
    sorted_edges = sorted(
        (
            {
                **dict(item),
                "input_ids": list(item.get("input_ids", item.get("inputs", ()))),
                "output_id": item.get("output_id") or item.get("output_claim_id"),
                "kind": item.get("kind") or item.get("operation") or "unknown",
            }
            for item in derivation_edges
        ),
        key=lambda item: str(item.get("edge_id", "")),
    )
    all_receipts = [*generative_receipts, *computation_receipts, *human_reviews]
    polarity_error = _validate_realized_polarity(
        answer, [*sorted_evidence, *sorted_edges, *all_receipts]
    )
    claim_ids = [str(item.get("claim_id", "")) for item in sorted_claims]
    if not all(claim_ids) or len(claim_ids) != len(set(claim_ids)):
        raise AnswerTrustError("claim IDs must be non-empty and unique")
    if not polarity_error and not sorted_evidence and not sorted_edges:
        polarity_error = "observed evidence and lineage inputs are absent"
    assessment_id = (
        "answer-trust-"
        + _digest(
            {
                "answer_digest": answer.get("digest"),
                "policy_digest": actual_policy_digest,
            }
        ).split(":", 1)[1][:16]
    )
    if polarity_error:
        return _seal(
            {
                "schema_version": ASSESSMENT_SCHEMA,
                "assessment_id": assessment_id,
                "polarity": "observed_only",
                "answer_digest": answer.get("digest"),
                "base_plan_digest": answer.get("base_plan_digest"),
                "evidence_manifest_digest": answer.get("evidence_manifest_digest"),
                "provenance_digest": answer.get("provenance_digest"),
                "policy_version": score_policy["policy_version"],
                "policy_digest": actual_policy_digest,
                "status": "not_calculable",
                "score": None,
                "score_interval": None,
                "band": None,
                "material_claim_coverage": 0.0,
                "blocking_reasons": [polarity_error],
                "claim_assessments": [],
                "evidence_atoms": [
                    _evidence_projection(item) for item in sorted_evidence
                ],
                "derivation_edges": [_edge_projection(item) for item in sorted_edges],
                "exemptions": [],
                "diagnostics": {},
                "binding": {},
                "denominator_frozen": True,
            }
        )
    exemptions = [
        {"claim_id": str(item.get("claim_id", "")), "reason": _claim_exemption(item)}
        for item in sorted_claims
        if _claim_exemption(item)
    ]
    material = [item for item in sorted_claims if not _claim_exemption(item)]
    graph, cycles = _lineage_graph(sorted_edges)
    receipts = {
        str(item.get("edge_id")): dict(item)
        for item in generative_receipts
        if item.get("edge_id")
    }
    computations = {
        str(item.get("edge_id") or item.get("receipt_id")): dict(item)
        for item in computation_receipts
        if item.get("edge_id") or item.get("receipt_id")
    }
    assessed = [
        _claim_assessment(
            item,
            sorted_evidence,
            sorted_edges,
            receipts,
            computations,
            graph,
            cycles,
            human_reviews,
            score_policy,
        )
        for item in material
    ]
    components = {
        str(item.get("component_id"))
        for item in answer.get("components", ())
        if item.get("component_id")
    }
    mapped = {
        component
        for item in sorted_claims
        for component in item.get("component_ids", ())
    }
    coverage = (
        1.0
        if not components
        else len(components.intersection(mapped)) / len(components)
    )
    claim_coverage = 1.0 if not material else len(assessed) / len(material)
    atomization_coverage = min(coverage, claim_coverage)
    lower = _weighted_harmonic(assessed, 0) * atomization_coverage
    upper = _weighted_harmonic(assessed, 1) * atomization_coverage
    critical = [item for item in assessed if item["release_critical"]]
    if critical:
        lower = min(lower, min(float(item["score_interval"][0]) for item in critical))
        upper = min(upper, min(float(item["score_interval"][1]) for item in critical))
    quality_failed = quality_assessment is not None and (
        quality_assessment.get("status") in {"failed", "blocked"}
        or quality_assessment.get("verdict") in {"fail", "failed", "blocked"}
    )
    provenance_summary = (provenance_reconciliation or {}).get("summary", {})
    provenance_failed = provenance_reconciliation is not None and (
        provenance_reconciliation.get("status") in {"failed", "mismatch"}
        or provenance_summary.get("release_blocking") is True
        or provenance_summary.get("complete") is False
    )
    if quality_failed or provenance_failed:
        upper = min(upper, 24.0)
        lower = min(lower, upper)
    interval_width = upper - lower
    fatal = (
        any(item["gates"] for item in assessed) or quality_failed or provenance_failed
    )
    incomplete = atomization_coverage < 1.0
    if fatal:
        status = "blocked"
    elif incomplete or interval_width > float(score_policy["interval_width_limit"]):
        status = "insufficient_evidence"
    else:
        status = "assessed"
    crisp_score = (
        lower
        if status in {"assessed", "blocked"}
        and math.isclose(lower, upper, abs_tol=1e-9)
        else None
    )
    display_score = crisp_score if crisp_score is not None else lower
    band = _band(display_score, score_policy)
    if band == "high_control" and any(
        item["score_interval"][0] < score_policy["critical_claim_threshold"]
        for item in critical
    ):
        band = "substantiated"
    count = len(assessed) or 1
    provenance_coverage = (provenance_reconciliation or {}).get("coverage")
    if provenance_coverage is None:
        matched = provenance_summary.get("matched_components")
        total = provenance_summary.get("total_components")
        if (
            isinstance(matched, (int, float))
            and isinstance(total, (int, float))
            and total
        ):
            provenance_coverage = matched / total
        else:
            reconciliation_components = (provenance_reconciliation or {}).get(
                "components", ()
            )
            if reconciliation_components:
                provenance_coverage = sum(
                    item.get("status") in {"matched", "complete", "observed"}
                    for item in reconciliation_components
                ) / len(reconciliation_components)
    if provenance_coverage is None:
        provenance_coverage = 1.0
    diagnostics = {
        "grounded_material_claim_coverage": sum(item["grounded"] for item in assessed)
        / count,
        "memory_only_claim_rate": sum(item["memory_only"] for item in assessed) / count,
        "unsupported_generative_addition_rate": sum(
            bool(item["unsupported_generative_additions"]) for item in assessed
        )
        / count,
        "citation_lineage_mismatch_rate": sum(
            item["citation_lineage_mismatch"] for item in assessed
        )
        / count,
        "preservation_failure_rate": sum(
            bool(item["preservation_failures"]) for item in assessed
        )
        / count,
        "observed_vs_planned_lineage_coverage": float(provenance_coverage),
        "weakest_claim_ids": [
            item["claim_id"]
            for item in sorted(assessed, key=lambda row: row["score_interval"][0])[:3]
        ],
        "weakest_release_critical_claim_ids": [
            item["claim_id"]
            for item in sorted(critical, key=lambda row: row["score_interval"][0])[:3]
        ],
        "applied_gates": sorted(
            (
                {**gate, "claim_id": item["claim_id"]}
                for item in assessed
                for gate in item["gates"]
            ),
            key=_canonical,
        ),
        "applied_caps": sorted(
            (
                {**cap, "claim_id": item["claim_id"]}
                for item in assessed
                for cap in item["caps"]
            ),
            key=_canonical,
        ),
        "remediation": sorted(
            {repair for item in assessed for repair in item["remediation"]}
        ),
    }
    composition_total = len(sorted_claims) or 1
    diagnostics["answer_content_composition"] = {
        "evidence_backed": sum(item["grounded"] for item in assessed)
        / composition_total,
        "deterministic": sum(
            item["claim_class"] == "deterministic_derivation" for item in assessed
        )
        / composition_total,
        "generative_but_verified": sum(
            item["dimensions"]["generative_containment"] == 1.0
            and any(
                edge.get("kind") in {"generative", "lossy", "semantic"}
                and str(edge.get("output_id")) in set(item["component_ids"])
                for edge in sorted_edges
            )
            for item in assessed
        )
        / composition_total,
        "hypothesis": sum(
            item["claim_class"] in {"hypothesis", "exploratory_hypothesis"}
            for item in assessed
        )
        / composition_total,
        "unknown_or_exempt": len(exemptions) / composition_total,
    }
    binding = {
        "answer_digest": answer["digest"],
        "claim_inventory_digest": _digest(sorted_claims),
        "evidence_digest": _digest(sorted_evidence),
        "derivation_digest": _digest(sorted_edges),
        "transformation_receipts_digest": _digest(
            sorted((dict(item) for item in generative_receipts), key=_canonical)
        ),
        "computation_receipts_digest": _digest(
            sorted((dict(item) for item in computation_receipts), key=_canonical)
        ),
        "provenance_reconciliation_digest": (
            _digest(provenance_reconciliation)
            if provenance_reconciliation is not None
            else None
        ),
        "quality_assessment_digest": (
            _digest(quality_assessment) if quality_assessment is not None else None
        ),
        "policy_digest": actual_policy_digest,
    }
    result = {
        "schema_version": ASSESSMENT_SCHEMA,
        "assessment_id": assessment_id,
        "polarity": "observed_only",
        "answer_digest": answer["digest"],
        "base_plan_digest": answer.get("base_plan_digest")
        or (provenance_reconciliation or {}).get("base_plan_digest"),
        "evidence_manifest_digest": answer.get("evidence_manifest_digest")
        or (provenance_reconciliation or {}).get("evidence_manifest_digest"),
        "provenance_digest": answer.get("provenance_digest")
        or (provenance_reconciliation or {}).get("digest"),
        "policy_version": score_policy["policy_version"],
        "policy_digest": actual_policy_digest,
        "status": status,
        "score": crisp_score,
        "score_interval": [lower, upper],
        "band": band,
        "material_claim_coverage": atomization_coverage,
        "denominator_frozen": True,
        "claim_assessments": assessed,
        "evidence_atoms": [_evidence_projection(item) for item in sorted_evidence],
        "derivation_edges": [_edge_projection(item) for item in sorted_edges],
        "exemptions": exemptions,
        "diagnostics": diagnostics,
        "binding": binding,
        "blocking_reasons": (["quality assessment failed"] if quality_failed else [])
        + (["provenance reconciliation failed"] if provenance_failed else []),
    }
    return _seal(result)


def invalidate_answer_trust(
    assessment: Mapping[str, Any], changed_digests: Mapping[str, str | None]
) -> dict[str, Any]:
    """Return deterministic invalidation findings for changed bound inputs."""

    binding = assessment.get("binding", {})
    changed = sorted(
        key
        for key, value in changed_digests.items()
        if key in binding and binding.get(key) != value
    )
    owners = {
        "answer_digest": "answer materializer",
        "claim_inventory_digest": "claim inventory compiler",
        "evidence_digest": "evidence intake",
        "derivation_digest": "lineage verifier",
        "transformation_receipts_digest": "claim-fidelity verifier",
        "computation_receipts_digest": "computation verifier",
        "provenance_reconciliation_digest": "provenance reconciler",
        "quality_assessment_digest": "quality assessor",
        "policy_digest": "trust policy owner",
    }
    claim_rows = assessment.get("claim_assessments", ())
    all_claim_ids = {str(item.get("claim_id")) for item in claim_rows}
    affected: set[str] = set()
    for key in changed:
        if key in {
            "answer_digest",
            "claim_inventory_digest",
            "evidence_digest",
            "provenance_reconciliation_digest",
            "quality_assessment_digest",
            "policy_digest",
        }:
            affected.update(all_claim_ids)
        elif key == "transformation_receipts_digest":
            affected.update(
                str(item.get("claim_id"))
                for item in claim_rows
                if item.get("dimensions", {}).get("generative_containment") != 1.0
                or item.get("preservation_failures")
            )
        elif key == "computation_receipts_digest":
            affected.update(
                str(item.get("claim_id"))
                for item in claim_rows
                if item.get("claim_class") == "deterministic_derivation"
            )
    return _seal(
        {
            "schema_version": INVALIDATION_SCHEMA,
            "assessment_digest": assessment.get("digest"),
            "valid": not changed,
            "changed_inputs": changed,
            "affected_claim_ids": sorted(affected),
            "reentry_owners": sorted({owners[key] for key in changed}),
            "required_action": "reassess affected claims" if changed else "none",
        }
    )


def build_trust_card(
    assessment: Mapping[str, Any],
    *,
    rollout_state: str = "advisory",
) -> dict[str, Any]:
    """Render a concise, chain-of-thought-free projection of an assessment."""

    claim_rows = assessment.get("claim_assessments", ())
    weaknesses = [
        {
            "claim_id": item.get("claim_id"),
            "score_interval": item.get("score_interval"),
            "gates": [gate.get("code") for gate in item.get("gates", ())],
            "caps": [cap.get("code") for cap in item.get("caps", ())],
            "remediation": item.get("remediation", ()),
        }
        for item in sorted(
            claim_rows, key=lambda row: row.get("score_interval", [0])[0]
        )[:3]
    ]
    rollout = resolve_answer_trust_rollout(rollout_state)
    return _seal(
        {
            "schema_version": TRUST_CARD_SCHEMA,
            "assessment_digest": assessment.get("digest"),
            "status": assessment.get("status"),
            "score": assessment.get("score"),
            "score_interval": assessment.get("score_interval"),
            "band": assessment.get("band"),
            "policy_version": assessment.get("policy_version"),
            "material_claim_coverage": assessment.get("material_claim_coverage"),
            "diagnostics": assessment.get("diagnostics", {}),
            "critical_weaknesses": weaknesses,
            "rollout_state": rollout["effective_state"],
            "user_visible": rollout["user_visible"],
            "interpretation": "Control posture for this exact answer; not a probability that its claims are true.",
        }
    )


def build_readiness_card(
    readiness: Mapping[str, Any],
    *,
    rollout_state: str = "advisory",
) -> dict[str, Any]:
    """Project score-free pre-execution controls for researcher communication."""

    if readiness.get("schema_version") != READINESS_SCHEMA:
        raise AnswerTrustError("readiness card requires answer-control-readiness/v1")
    if readiness.get("realized_trust_score") is not None or "score" in readiness:
        raise AnswerTrustError("prospective readiness cannot contain a realized score")
    rollout = resolve_answer_trust_rollout(rollout_state)
    findings = [
        {
            "finding_id": row.get("finding_id"),
            "severity": row.get("severity"),
            "plan_location": row.get("plan_location"),
            "message": row.get("message"),
            "repair": (row.get("proposed_todo") or {}).get("action"),
        }
        for row in readiness.get("findings", ())
    ]
    return _seal(
        {
            "schema_version": "lunar.planner.answer-control-readiness-card/v1",
            "readiness_digest": readiness.get("digest"),
            "attainable_control_band": readiness.get("attainable_control_band"),
            "claims_considered": readiness.get("claims_considered", 0),
            "required_receipts": list(readiness.get("required_receipts", ())),
            "control_gaps": findings,
            "rollout_state": rollout["effective_state"],
            "user_visible": rollout["user_visible"],
            "realized_trust_score": None,
            "interpretation": (
                "Prospective control readiness only; planned retrieval, verification, "
                "and review are not observed evidence or an answer trust score."
            ),
        }
    )


__all__ = [
    "ASSESSMENT_SCHEMA",
    "AnswerTrustError",
    "DEFAULT_POLICY",
    "INVALIDATION_SCHEMA",
    "READINESS_SCHEMA",
    "ROLLOUT_STATES",
    "TRUST_CARD_SCHEMA",
    "assess_answer_trust",
    "build_answer_control_readiness",
    "build_readiness_card",
    "build_trust_card",
    "invalidate_answer_trust",
    "resolve_answer_trust_rollout",
]
