# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0

"""Pure post-plan evidence and determinism verification.

The verifier consumes an already sealed workflow instantiation and returns an
additive, content-addressed sidecar.  It deliberately has no filesystem,
network, subprocess, installation, persistence, or workflow-execution path.
Inputs describe *planned* evidence and computation; they are never promoted to
observed execution merely because they appear in the verification context.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict, deque
from collections.abc import Iterable, Mapping, Sequence
from copy import deepcopy
from typing import Any

SCHEMA_VERSION = "lunar.planner.post-plan-evidence-verification/v1"
INVALIDATION_SCHEMA = "lunar.planner.epistemic-verification-invalidation/v1"
SUMMARY_EVENT_SCHEMA = "lunar.planner.reasoning-event/v1"
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")

_POSTURE_RANK = {
    "unknown": 0,
    "hypothesis": 1,
    "observed": 2,
    "computed": 2,
    "associated": 3,
    "causal": 4,
    "recommendation": 5,
}

_REUSE_OWNER = {
    "exact": "deterministic-claim-anchor-compiler",
    "symbolic": "provenance-rule-materializer",
    "statistical": "methods-provenance-auditor",
    "generative": "claim-fidelity-verifier",
    "human": "evidence-directness-claim-gater",
}


def _canonical(value: Any) -> str:
    """Canonical."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(value: Any) -> str:
    """Digest."""
    return "sha256:" + hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _seal(value: Mapping[str, Any]) -> dict[str, Any]:
    """Seal."""
    result = deepcopy(dict(value))
    result.pop("digest", None)
    result["digest"] = _digest(result)
    return result


def _plan_digest(plan: Mapping[str, Any]) -> str:
    """Plan digest."""
    payload = {key: value for key, value in plan.items() if key != "digest"}
    return _digest(payload)


def _stable_id(prefix: str, value: Any) -> str:
    """Stable id."""
    return f"{prefix}-{_digest(value).split(':', 1)[1][:16]}"


def _strings(value: Any) -> list[str]:
    """Strings."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        result: list[str] = []
        for key in sorted(value, key=str):
            result.extend(_strings(value[key]))
        return result
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        result = []
        for item in value:
            result.extend(_strings(item))
        return result
    return []


def _normalized_predicate(text: str) -> str:
    """Normalized predicate."""
    return re.sub(r"\s+", " ", text.strip()).rstrip(".")


def _classify_assertion(text: str) -> tuple[str, str]:
    """Classify assertion."""
    lowered = text.casefold()
    if re.search(
        r"\b(?:unknown|unresolved|not available|unavailable|not yet known)\b", lowered
    ):
        return "unknown", "unknown"
    if re.search(
        r"\b(?:hypothes(?:is|es|ize)|candidate mechanism|exploratory|proposed explanation)\b",
        lowered,
    ):
        return "exploratory_hypothesis", "hypothesis"
    if re.search(
        r"\b(?:must|shall|required constraint|user requires|preserve|do not)\b", lowered
    ):
        return "user_constraint", "unknown"
    if re.search(
        r"^\s*(?:plan|design|build|create|produce|generate|normalize|extract|query|retrieve|analy[sz]e|compile|render|write|test|validate|verify)\b"
        r"|\b(?:workflow|pipeline)\b[^.;]{0,120}\bto\b"
        r"|\b(?:will run|to run|prospective|future)\b",
        lowered,
    ):
        return "planned_future_action", "unknown"
    if re.search(
        r"\b(?:executed|completed|retrieved|queried|downloaded|ran successfully|was generated)\b",
        lowered,
    ):
        return "execution_status", "observed"
    if re.search(
        r"\b(?:caus(?:e|es|al)|treatment recommendation|should receive|clinical action)\b",
        lowered,
    ):
        return "scientific_synthesis", (
            "causal"
            if "recommend" not in lowered and "should receive" not in lowered
            else "recommendation"
        )
    if re.search(
        r"\b(?:associated|association|correlat|odds ratio|hazard ratio|p[- ]?value|confidence interval)\b",
        lowered,
    ):
        return "statistical_result", "associated"
    if re.search(
        r"\b(?:sum|mean|median|ratio|count|converted|normalized|derived|computed)\b",
        lowered,
    ):
        return "deterministic_derivation", "computed"
    if re.search(
        r"\b(?:entailed|axiom|ontology|constraint|temporal order|interval)\b", lowered
    ):
        return "symbolic_consequence", "computed"
    if re.search(
        r"\b(?:value|field|row|cell|record|sample size|participants|events)\b", lowered
    ):
        return "extracted_fact", "observed"
    return "scientific_synthesis", "unknown"


def _requested_ceiling(text: str, posture: str) -> str:
    """Requested ceiling."""
    lowered = text.casefold()
    if re.search(
        r"\b(?:recommend|should receive|clinical action|treatment selection)\b", lowered
    ):
        return "recommendation"
    if re.search(r"\bcaus(?:e|es|al)\b", lowered):
        return "causal"
    if re.search(r"\b(?:associated|association|correlat)\b", lowered):
        return "associated"
    return posture


def _compile_claim_atoms(
    plan: Mapping[str, Any], requirement_ledger: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """Compile claim atoms."""
    requirements = {
        str(row.get("requirement_id")): dict(row)
        for row in requirement_ledger.get("requirements", ())
        if isinstance(row, Mapping) and row.get("status", "active") == "active"
    }
    nodes = sorted(
        (dict(row) for row in plan.get("nodes", ()) if isinstance(row, Mapping)),
        key=lambda row: str(row.get("node_id", "")),
    )
    claims: list[dict[str, Any]] = []
    covered: set[str] = set()
    for node in nodes:
        requirement_ids = sorted(
            {str(value) for value in node.get("requirement_ids", ()) if value}
            or (
                {str(node.get("requirement_id"))}
                if node.get("requirement_id")
                else set()
            )
        )
        covered.update(requirement_ids)
        criteria = [
            str(value)
            for value in node.get("correctness_criteria", ())
            if str(value).strip()
        ]
        for requirement_id in requirement_ids or ["unbound"]:
            requirement = requirements.get(requirement_id, {})
            text = str(
                requirement.get("active_text")
                or requirement.get("text")
                or requirement.get("desired_output")
                or node.get("output_type")
                or "unknown planned output"
            )
            assertion_kind, posture = _classify_assertion(text)
            claim_key = {
                # Claim identity survives plan resealing when its semantic
                # owner is unchanged. Semantic edits still alter the sealed
                # overlay and the instantiation structure digest; the stable
                # claim ID lets refinement retain evidence across status-only
                # continuation turns.
                "node_id": node.get("node_id"),
                "requirement_id": requirement_id,
            }
            claims.append(
                {
                    "claim_id": _stable_id("claim", claim_key),
                    "plan_location": f"/nodes/{node.get('node_id', 'unknown')}",
                    "requirement_ids": (
                        [requirement_id] if requirement_id != "unbound" else []
                    ),
                    "node_id": (
                        str(node.get("node_id")) if node.get("node_id") else None
                    ),
                    "output_type": (
                        str(node.get("output_type"))
                        if node.get("output_type") is not None
                        else None
                    ),
                    "source_turn_indices": (
                        [int(requirement["source_turn_index"])]
                        if isinstance(requirement.get("source_turn_index"), int)
                        else []
                    ),
                    "normalized_predicate": _normalized_predicate(text),
                    "assertion_kind": assertion_kind,
                    "claim_posture": posture,
                    "materiality": "material",
                    "consumer": str(requirement.get("consumer", "workflow consumer")),
                    "intended_use": str(
                        requirement.get("desired_output")
                        or node.get("output_type")
                        or "planned workflow output"
                    ),
                    "requested_ceiling": _requested_ceiling(text, posture),
                    "prohibited_promotions": [
                        "planned work to observed execution",
                        "hypothesis to established fact without new evidence",
                        "association to causality without an identified design",
                    ],
                    "correctness_criteria": sorted(set(criteria)),
                }
            )
    for requirement_id in sorted(set(requirements) - covered):
        requirement = requirements[requirement_id]
        text = str(
            requirement.get("active_text")
            or requirement.get("text")
            or requirement.get("desired_output")
            or "unresolved requirement"
        )
        assertion_kind, posture = _classify_assertion(text)
        claims.append(
            {
                "claim_id": _stable_id(
                    "claim",
                    {
                        "base_plan_digest": plan.get("digest"),
                        "requirement_id": requirement_id,
                        "predicate": text,
                    },
                ),
                "plan_location": f"/requirements/{requirement_id}",
                "requirement_ids": [requirement_id],
                "node_id": None,
                "output_type": (
                    str(requirement.get("desired_output"))
                    if requirement.get("desired_output") is not None
                    else None
                ),
                "source_turn_indices": (
                    [int(requirement["source_turn_index"])]
                    if isinstance(requirement.get("source_turn_index"), int)
                    else []
                ),
                "normalized_predicate": _normalized_predicate(text),
                "assertion_kind": assertion_kind,
                "claim_posture": posture,
                "materiality": "material",
                "consumer": str(requirement.get("consumer", "workflow consumer")),
                "intended_use": str(
                    requirement.get("desired_output", "unresolved workflow obligation")
                ),
                "requested_ceiling": _requested_ceiling(text, posture),
                "prohibited_promotions": ["unowned requirement to delivered result"],
                "correctness_criteria": sorted(
                    {
                        str(value)
                        for value in requirement.get("correctness_criteria", ())
                    }
                ),
            }
        )
    return sorted(claims, key=lambda row: row["claim_id"])


def _method_for_claim(claim: Mapping[str, Any]) -> tuple[str, str, list[str], bool]:
    """Method for claim."""
    kind = str(claim["assertion_kind"])
    posture = str(claim["claim_posture"])
    if posture == "recommendation":
        return (
            "human",
            "value-laden or consequential recommendation requires named human authority",
            ["generative model as final authority"],
            True,
        )
    if kind in {
        "extracted_fact",
        "deterministic_derivation",
        "execution_status",
        "user_constraint",
        "planned_future_action",
        "unknown",
    }:
        return (
            "exact",
            "identity, state, constraint, extraction, or transform semantics are exactly checkable",
            ["generative adjudication of an exact fact"],
            False,
        )
    if kind == "symbolic_consequence":
        return (
            "symbolic",
            "the conclusion is relative to explicit rules, premises, or constraints",
            ["free-form generation instead of entailment checking"],
            False,
        )
    if kind == "statistical_result":
        return (
            "statistical",
            "the assertion requires an estimand, uncertainty, assumptions, and diagnostics",
            ["semantic confidence as a statistical estimate"],
            False,
        )
    return (
        "generative",
        "semantic synthesis or exploratory interpretation is not fully specified by exact rules",
        ["new factual specifics outside allowed evidence", "producer-only self-review"],
        True,
    )


def _authority_profile(claim: Mapping[str, Any]) -> dict[str, Any]:
    """Authority profile."""
    text = str(claim["normalized_predicate"]).casefold()
    kind = str(claim["assertion_kind"])
    if kind == "user_constraint":
        category, preferred, ceiling = (
            "user_preference",
            ["user statement"],
            "constraint only; no external factual authority",
        )
    elif kind == "execution_status":
        category, preferred, ceiling = (
            "local_execution",
            ["authenticated run artifact", "retrospective provenance event"],
            "observed execution state only",
        )
    elif re.search(r"\b(?:law|regulation|regulatory|gdpr|ai act|requirement)\b", text):
        category, preferred, ceiling = (
            "law_or_regulation",
            ["issuing authority", "effective official text"],
            "obligation for the cited jurisdiction, version, and date",
        )
    elif re.search(r"\b(?:package|api|library|version|function)\b", text):
        category, preferred, ceiling = (
            "software_behavior",
            ["official documentation", "official package registry"],
            "documented behavior for the cited version",
        )
    elif kind in {"extracted_fact", "statistical_result"}:
        category, preferred, ceiling = (
            "empirical_result",
            ["primary study", "primary dataset", "authenticated result artifact"],
            "tested design, population, specimen, and endpoint",
        )
    else:
        category, preferred, ceiling = (
            "scientific_synthesis",
            ["primary evidence", "systematic review or guideline for consensus"],
            "bounded synthesis; primary numeric details require primary evidence",
        )
    return {
        "profile_id": _stable_id(
            "authority", {"claim": claim["claim_id"], "category": category}
        ),
        "claim_id": claim["claim_id"],
        "assertion_category": category,
        "preferred_authority_classes": preferred,
        "inclusion_rules": [
            "source identity and version are explicit",
            "source scope is applicable to the claim qualifiers",
        ],
        "exclusion_rules": [
            "unresolvable source",
            "unauthorized content",
            "retrieval hint presented as evidence",
        ],
        "required_source_roles": ["direct support or declared contextual role"],
        "directness_rule": "track direct, proof-derived, distributed, partial, contradicted, absent, and retrieval-only separately",
        "currency_rule": "record release or effective date and reverify when the claim depends on current state",
        "conflict_search_rule": "retain material counterevidence and conflicting authoritative records",
        "stop_rule": "stop when each predicate is supported, unresolved, contradicted, or the frozen budget is exhausted",
        "maximum_ceiling": ceiling,
    }


def _evidence_atoms(
    context: Mapping[str, Any], claims: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """Evidence atoms."""
    rows = context.get("evidence_atoms", ())
    result: list[dict[str, Any]] = []
    for index, source in enumerate(rows if isinstance(rows, Sequence) else ()):
        if not isinstance(source, Mapping):
            continue
        row = dict(source)
        identity = str(row.get("source_id", f"source-{index + 1}"))
        locator = str(row.get("locator", ""))
        content_digest = row.get("content_digest")
        valid_digest = isinstance(content_digest, str) and bool(
            _DIGEST.fullmatch(content_digest)
        )
        requirement_ids = {
            str(value) for value in row.get("applicable_requirement_ids", ())
        }
        applicable_claim_ids = {
            str(value) for value in row.get("applicable_claim_ids", ())
        }
        applicable_claim_ids.update(
            str(claim["claim_id"])
            for claim in claims
            if requirement_ids & set(map(str, claim.get("requirement_ids", ())))
        )
        result.append(
            {
                "evidence_id": str(
                    row.get("evidence_id")
                    or _stable_id(
                        "evidence",
                        {
                            "source_id": identity,
                            "locator": locator,
                            "content_digest": content_digest,
                        },
                    )
                ),
                "source_id": identity,
                "owner_or_issuer": str(row.get("owner_or_issuer", "unknown")),
                "source_class": str(row.get("source_class", "bounded_reference")),
                "release_or_date": (
                    str(row.get("release_or_date"))
                    if row.get("release_or_date") is not None
                    else None
                ),
                "content_digest": str(content_digest) if valid_digest else None,
                "authorized": bool(row.get("authorized", False)),
                "retrieval_snapshot_digest": (
                    str(row.get("retrieval_snapshot_digest"))
                    if row.get("retrieval_snapshot_digest") is not None
                    else None
                ),
                "independence_cluster": str(row.get("independence_cluster", identity)),
                "locator": locator,
                "access_class": str(row.get("access_class", "metadata")),
                "asserted_predicate": str(row.get("asserted_predicate", "")),
                "applicable_claim_ids": sorted(applicable_claim_ids),
                "source_role": str(row.get("source_role", "candidate")),
                "directness": str(row.get("directness", "retrieval_only")),
                "authority_basis": str(row.get("authority_basis", "unreviewed")),
                "extraction_mode": str(row.get("extraction_mode", "planned")),
                "prompt_injection_quarantined": bool(
                    row.get("prompt_injection_quarantined", True)
                ),
                "support_class": str(row.get("support_class", "retrieval_only")),
                "locator_valid": bool(locator and valid_digest),
            }
        )
    return sorted(result, key=lambda row: row["evidence_id"])


def _computation_atom(
    claim: Mapping[str, Any], method: str, reason: str
) -> dict[str, Any]:
    """Computation atom."""
    determinism = {
        "exact": "pure",
        "symbolic": "pure",
        "statistical": "stochastic_estimated",
        "generative": "semantic_generative",
        "human": "human",
    }[method]
    return {
        "computation_id": _stable_id(
            "computation", {"claim": claim["claim_id"], "method": method}
        ),
        "claim_id": claim["claim_id"],
        "method_class": method,
        "assignment_reason": reason,
        "provider_identity": "planner-selected-reviewed-provider",
        "provider_version": None,
        "environment_digest": None,
        "permissions": ["planning_only"],
        "input_types": ["typed evidence or prior claim"],
        "output_type": str(claim.get("output_type") or "verification result"),
        "parameters": {},
        "seed": None,
        "numerical_tolerance": None,
        "determinism_class": determinism,
        "estimand": "required before execution" if method == "statistical" else None,
        "assumptions": ["provider availability and version must be preflighted"],
        "invariants": ["no claim promotion above the admitted evidence ceiling"],
        "fixtures": ["missing input", "conflicting evidence", "provider unavailable"],
        "replication_rule": (
            "exact replay"
            if determinism == "pure"
            else "record seed or repeated uncertainty assessment"
        ),
        "provider_unavailable_behavior": "typed unavailable; do not silently substitute",
    }


def _edge_checks(plan: Mapping[str, Any]) -> tuple[list[dict[str, Any]], set[str]]:
    """Edge checks."""
    nodes = [dict(row) for row in plan.get("nodes", ()) if isinstance(row, Mapping)]
    edges = [dict(row) for row in plan.get("edges", ()) if isinstance(row, Mapping)]
    node_ids = [str(row.get("node_id")) for row in nodes]
    node_set = set(node_ids)
    checks: list[dict[str, Any]] = []
    failures: set[str] = set()
    duplicate = len(node_ids) != len(node_set)
    checks.append(
        {
            "check_id": "node-identity-unique",
            "kind": "identity",
            "status": "fail" if duplicate else "pass",
            "target": "/nodes",
            "detail": "node IDs must be unique",
        }
    )
    if duplicate:
        failures.add("/nodes")
    graph: dict[str, list[str]] = defaultdict(list)
    indegree = {node_id: 0 for node_id in node_set}
    for edge in sorted(edges, key=lambda row: str(row.get("edge_id", ""))):
        left, right = str(edge.get("from_node")), str(edge.get("to_node"))
        valid = left in node_set and right in node_set
        checks.append(
            {
                "check_id": f"edge-endpoints-{edge.get('edge_id', 'unknown')}",
                "kind": "typed_join",
                "status": "pass" if valid else "fail",
                "target": f"/edges/{edge.get('edge_id', 'unknown')}",
                "detail": "edge endpoints must resolve to plan nodes",
            }
        )
        if not valid:
            failures.add(f"/edges/{edge.get('edge_id', 'unknown')}")
        else:
            graph[left].append(right)
            indegree[right] += 1
    queue = deque(sorted(node for node, degree in indegree.items() if degree == 0))
    visited = 0
    while queue:
        node = queue.popleft()
        visited += 1
        for target in sorted(graph[node]):
            indegree[target] -= 1
            if indegree[target] == 0:
                queue.append(target)
    acyclic = visited == len(node_set)
    checks.append(
        {
            "check_id": "workflow-dag-acyclic",
            "kind": "dag",
            "status": "pass" if acyclic else "fail",
            "target": "/edges",
            "detail": "workflow graph must be acyclic",
        }
    )
    if not acyclic:
        failures.add("/edges")
    return sorted(checks, key=lambda row: row["check_id"]), failures


def _claim_support(
    claim: Mapping[str, Any],
    evidence: Sequence[Mapping[str, Any]],
    plan: Mapping[str, Any],
) -> tuple[str, list[str], str, str]:
    """Claim support."""
    applicable = [
        row
        for row in evidence
        if claim["claim_id"] in row.get("applicable_claim_ids", ())
    ]
    authorized = [
        row for row in applicable if row.get("authorized") and row.get("locator_valid")
    ]
    conflicts = [
        row for row in applicable if row.get("support_class") == "contradicted"
    ]
    kind = str(claim["assertion_kind"])
    if kind in {"user_constraint", "planned_future_action", "unknown"}:
        return (
            "pass",
            [],
            "not_applicable",
            "typed non-factual obligation is preserved without unnecessary citation",
        )
    if kind == "exploratory_hypothesis":
        return (
            "pass_with_caveat",
            [str(row["evidence_id"]) for row in authorized],
            "hypothesis",
            "exploration is allowed with provenance, rivals, uncertainty, and prohibited factual promotion",
        )
    if conflicts:
        return (
            "revise_plan",
            [str(row["evidence_id"]) for row in authorized],
            "unknown",
            "material contradictory evidence must remain visible and be adjudicated",
        )
    if authorized:
        directness = {str(row.get("directness")) for row in authorized}
        ceiling = "observed" if "direct" in directness else "hypothesis"
        return (
            "pass" if "direct" in directness else "pass_with_caveat",
            [str(row["evidence_id"]) for row in authorized],
            ceiling,
            "authorized locator-bound evidence is planned",
        )
    component_text = " ".join(
        str((row.get("component") or {}).get("id", ""))
        for row in plan.get("nodes", ())
        if isinstance(row, Mapping)
    ).casefold()
    has_evidence_stage = any(
        token in component_text
        for token in (
            "evidence",
            "source",
            "query",
            "retriev",
            "literature",
            "provenance",
        )
    )
    if has_evidence_stage and kind != "execution_status":
        return (
            "defer",
            [],
            "unknown",
            "the plan contains a prospective evidence stage; exact grounding remains an execution obligation",
        )
    return (
        "block" if kind == "execution_status" else "revise_plan",
        [],
        "unknown",
        "no exact authorized evidence path or evidence-producing stage is bound",
    )


def _ceiling_exceeded(requested: str, supported: str) -> bool:
    """Ceiling exceeded."""
    if supported in {"not_applicable", "unknown"}:
        return requested not in {"unknown", "hypothesis"}
    return _POSTURE_RANK.get(requested, 99) > _POSTURE_RANK.get(supported, 0)


def _verification_context(value: Mapping[str, Any] | None) -> dict[str, Any]:
    """Verification context."""
    source = dict(value or {})
    allowed = {
        "external_source_plan",
        "external_capability_coverage",
        "package_search_receipt",
        "evidence_atoms",
        "computation_receipts",
        "authority_policy",
    }
    unexpected = sorted(set(source) - allowed)
    if unexpected:
        raise ValueError(
            f"verification_context contains unsupported fields: {unexpected}"
        )
    normalized = {key: deepcopy(source[key]) for key in sorted(source)}
    for collection in ("evidence_atoms", "computation_receipts"):
        if isinstance(normalized.get(collection), Sequence) and not isinstance(
            normalized[collection], (str, bytes, bytearray)
        ):
            normalized[collection] = sorted(
                (deepcopy(value) for value in normalized[collection]), key=_canonical
            )
    return {
        "schema_version": "lunar.planner.verification-context/v1",
        "receipt_digests": {
            key: _digest(value)
            for key, value in normalized.items()
            if key not in {"evidence_atoms", "computation_receipts"}
        },
        "inputs": normalized,
        "network_performed": False,
        "retrieval_performed": False,
        "execution_performed": False,
        "digest": _digest(normalized),
    }


def build_post_plan_verification(
    workflow_instantiation: Mapping[str, Any],
    requirement_ledger: Mapping[str, Any],
    *,
    verification_context: Mapping[str, Any] | None = None,
    enabled: bool = True,
) -> dict[str, Any] | None:
    """Build a deterministic, non-mutating verification sidecar.

    ``None`` is the explicit disabled result, allowing callers to preserve their
    previous result byte-for-byte.  Enabled verification always returns a
    sidecar and never mutates either input mapping.
    """

    if not enabled:
        return None
    plan = deepcopy(dict(workflow_instantiation))
    ledger = deepcopy(dict(requirement_ledger))
    base_plan_digest = str(plan.get("digest", ""))
    computed_plan_digest = _plan_digest(plan)
    context = _verification_context(verification_context)
    claims = _compile_claim_atoms(plan, ledger)
    evidence = _evidence_atoms(context["inputs"], claims)
    deterministic_checks, structural_failures = _edge_checks(plan)
    plan_digest_valid = (
        bool(_DIGEST.fullmatch(base_plan_digest))
        and base_plan_digest == computed_plan_digest
    )
    deterministic_checks.append(
        {
            "check_id": "base-plan-digest-integrity",
            "kind": "hash",
            "status": "pass" if plan_digest_valid else "fail",
            "target": "/digest",
            "detail": "the sidecar must bind the exact canonical plan bytes",
        }
    )
    method_assignments: list[dict[str, Any]] = []
    computations: list[dict[str, Any]] = []
    authority_profiles: list[dict[str, Any]] = []
    obligations: list[dict[str, Any]] = []
    matrix: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    repairs: list[dict[str, Any]] = []
    tests: list[dict[str, Any]] = list(deterministic_checks)
    if not plan_digest_valid:
        findings.append(
            {
                "finding_id": "finding-base-plan-digest",
                "claim_id": None,
                "target": "/digest",
                "severity": "block",
                "disposition": "block",
                "code": "base_plan_digest_mismatch",
                "message": "The supplied workflow instantiation is unsealed or was mutated.",
                "owner": "planner runtime",
            }
        )
    for target in sorted(structural_failures):
        findings.append(
            {
                "finding_id": _stable_id(
                    "finding", {"target": target, "code": "invalid_plan_structure"}
                ),
                "claim_id": None,
                "target": target,
                "severity": "block",
                "disposition": "block",
                "code": "invalid_plan_structure",
                "message": "An exact workflow graph invariant failed.",
                "owner": "planner runtime",
            }
        )

    for claim in claims:
        method, reason, prohibited, separation = _method_for_claim(claim)
        assignment = {
            "claim_id": claim["claim_id"],
            "method_class": method,
            "reason": reason,
            "least_flexible_adequate": True,
            "stricter_method_inapplicable_reason": (
                None if method == "exact" else reason
            ),
            "prohibited_fallbacks": prohibited,
            "reuse_owner_skill": _REUSE_OWNER[method],
        }
        method_assignments.append(assignment)
        computations.append(_computation_atom(claim, method, reason))
        authority = _authority_profile(claim)
        authority_profiles.append(authority)
        disposition, evidence_ids, supported_ceiling, rationale = _claim_support(
            claim, evidence, plan
        )
        if _ceiling_exceeded(str(claim["requested_ceiling"]), supported_ceiling):
            disposition = "revise_plan" if disposition != "block" else disposition
            rationale = f"{rationale}; requested {claim['requested_ceiling']} exceeds supported {supported_ceiling} ceiling"
        matrix_row = {
            "claim_id": claim["claim_id"],
            "evidence_ids": sorted(evidence_ids),
            "authority_profile_id": authority["profile_id"],
            "method_class": method,
            "supported_ceiling": supported_ceiling,
            "requested_ceiling": claim["requested_ceiling"],
            "contradiction_present": any(
                row["evidence_id"] in evidence_ids
                and row["support_class"] == "contradicted"
                for row in evidence
            ),
            "independence_clusters": sorted(
                {
                    str(row["independence_cluster"])
                    for row in evidence
                    if row["evidence_id"] in evidence_ids
                }
            ),
            "disposition": disposition,
            "rationale": rationale,
        }
        matrix.append(matrix_row)
        severity = (
            "block"
            if disposition == "block"
            else ("repair" if disposition == "revise_plan" else "advisory")
        )
        obligation_id = _stable_id(
            "obligation", {"claim": claim["claim_id"], "method": method}
        )
        obligation = {
            "obligation_id": obligation_id,
            "claim_id": claim["claim_id"],
            "target": claim["plan_location"],
            "method_class": method,
            "pass_condition": "claim remains within its source, derivation, authority, and uncertainty ceiling",
            "required_evidence_ids": sorted(evidence_ids),
            "severity": severity,
            "failure_consequence": "withhold or repair only this claim and its dependent derivations",
            "reentry_owner": _REUSE_OWNER[method],
            "invalidation_inputs": sorted(
                {
                    "base_plan_digest",
                    *claim["requirement_ids"],
                    authority["profile_id"],
                    *evidence_ids,
                }
            ),
            "producer_evaluator_separation_required": separation,
        }
        obligations.append(obligation)
        tests.append(
            {
                "check_id": f"verify-{claim['claim_id']}",
                "kind": method,
                "status": "planned",
                "target": claim["plan_location"],
                "detail": obligation["pass_condition"],
            }
        )
        if disposition in {"revise_plan", "block", "inconclusive"}:
            code = (
                "claim_grounding_missing"
                if not evidence_ids
                else "claim_ceiling_or_conflict"
            )
            finding = _seal(
                {
                    "finding_id": _stable_id(
                        "finding", {"claim": claim["claim_id"], "code": code}
                    ),
                    "claim_id": claim["claim_id"],
                    "target": claim["plan_location"],
                    "severity": severity,
                    "disposition": disposition,
                    "code": code,
                    "message": rationale,
                    "owner": _REUSE_OWNER[method],
                }
            )
            findings.append(finding)
            repairs.append(
                {
                    "repair_id": _stable_id("repair", finding["finding_id"]),
                    "finding_id": finding["finding_id"],
                    "operation": "propose_add_or_tighten_verification",
                    "target": claim["plan_location"],
                    "owner": _REUSE_OWNER[method],
                    "proposed_value": {
                        "method_class": method,
                        "authority_profile_id": authority["profile_id"],
                        "maximum_claim_ceiling": supported_ceiling,
                    },
                    "mutates_base_plan": False,
                    "done_when": obligation["pass_condition"],
                }
            )

    derivation_edges = [
        {
            "edge_id": _stable_id(
                "derivation", {"claim": row["claim_id"], "method": row["method_class"]}
            ),
            "input_evidence_ids": list(row["evidence_ids"]),
            "input_claim_ids": [],
            "output_claim_id": row["claim_id"],
            "operation": row["method_class"],
            "assumptions": [
                "qualifiers and provenance survive the planned transformation"
            ],
            "monotonic": row["method_class"] in {"exact", "symbolic"},
            "lossy": row["method_class"] in {"generative", "statistical", "human"},
            "verifier": _REUSE_OWNER[row["method_class"]],
            "preserved_qualifiers": [
                "population",
                "specimen",
                "intervention",
                "comparator",
                "outcome",
                "time",
                "uncertainty",
            ],
        }
        for row in matrix
    ]
    symbolic_constraint_contracts = [
        {
            "contract_id": _stable_id("symbolic", {"claim": claim["claim_id"]}),
            "claim_id": claim["claim_id"],
            "ontology_constraints": [],
            "namespace_constraints": [
                "all identifiers must retain an explicit namespace"
            ],
            "temporal_constraints": [
                "temporal conclusions require declared interval and ordering semantics"
            ],
            "protocol_constraints": [
                "protocol-relative conclusions must name the governing protocol version"
            ],
            "scope_constraints": [str(claim["intended_use"])],
            "premises": [str(claim["normalized_predicate"])],
            "claim_ceiling": str(claim["requested_ceiling"]),
            "closed_world_assumption": False,
            "failure_consequence": "withhold only this symbolic conclusion until its premises and grounding links pass",
        }
        for claim in claims
        if next(
            row for row in method_assignments if row["claim_id"] == claim["claim_id"]
        )["method_class"]
        == "symbolic"
    ]
    adapter_semantics = {
        "schema": "validate declared document shape and reject unknown critical fields",
        "registry": "resolve declared identifiers against the admitted registry snapshot",
        "hash": "bind immutable inputs and outputs with canonical content digests",
        "version": "bind provider, method, source, and protocol versions",
        "identity": "preserve entity identity and namespace through transformations",
        "join": "verify typed producer-consumer compatibility and join cardinality",
        "unit": "check dimension, unit vocabulary, and conversion provenance",
        "arithmetic": "recompute declared exact arithmetic with explicit tolerance",
        "set": "check membership, uniqueness, coverage, and difference operations",
        "dag": "check endpoint resolution and acyclicity",
        "artifact": "check existence, declared media/type, digest, and terminal binding",
        "extraction": "compare extracted values to exact source locators",
        "evidence_completeness": "ensure every material factual claim has evidence or a prospective evidence obligation",
    }
    deterministic_adapter_contracts = [
        {
            "adapter_id": f"deterministic-{name}",
            "kind": name,
            "semantics": semantics,
            "status": (
                "checked"
                if name in {"hash", "join", "dag", "artifact", "evidence_completeness"}
                else "planned_when_applicable"
            ),
            "fallback": "not_applicable_or_explicit_unknown",
            "generative_substitution_allowed": False,
        }
        for name, semantics in sorted(adapter_semantics.items())
    ]
    uncertainty_vectors = [
        {
            "claim_id": claim["claim_id"],
            "measurement": "unassessed until evidence exists",
            "sampling": "unassessed until study geometry exists",
            "model": "method-dependent",
            "stochastic": "required for stochastic or generative methods",
            "source_disagreement": (
                "present"
                if next(row for row in matrix if row["claim_id"] == claim["claim_id"])[
                    "contradiction_present"
                ]
                else "not_observed_in_planning_context"
            ),
            "applicability": "bounded by the authority profile",
            "missing_evidence": (
                "present"
                if not next(
                    row for row in matrix if row["claim_id"] == claim["claim_id"]
                )["evidence_ids"]
                and claim["assertion_kind"]
                not in {"user_constraint", "planned_future_action", "unknown"}
                else "not_required_or_planned"
            ),
        }
        for claim in claims
    ]
    evidence_clusters = [
        {
            "cluster_id": cluster_id,
            "evidence_ids": sorted(str(row["evidence_id"]) for row in rows),
            "support_classes": sorted({str(row["support_class"]) for row in rows}),
            "contains_contradiction": any(
                row["support_class"] == "contradicted" for row in rows
            ),
            "counts_as_independent_sources": 1,
        }
        for cluster_id, rows in sorted(
            (
                (
                    cluster_id,
                    [
                        row
                        for row in evidence
                        if row["independence_cluster"] == cluster_id
                    ],
                )
                for cluster_id in sorted(
                    {str(row["independence_cluster"]) for row in evidence}
                )
            ),
            key=lambda item: item[0],
        )
    ]
    generative_envelopes = [
        {
            "claim_id": row["claim_id"],
            "allowed_evidence_ids": list(row["evidence_ids"]),
            "allowed_operations": [
                "bounded synthesis",
                "paraphrase fidelity",
                "rival explanations",
                "hypothesis formation",
            ],
            "prohibited_promotions": [
                "new factual specifics",
                "unanchored numeric values",
                "hypothesis to observed fact",
            ],
            "output_schema_required": True,
            "abstention_required": True,
            "independent_fidelity_verifier": "claim-fidelity-verifier",
            "producer_may_self_approve": False,
        }
        for row in matrix
        if row["method_class"] == "generative"
    ]
    counts = defaultdict(int)
    for row in matrix:
        counts[str(row["disposition"])] += 1
    if counts["block"]:
        status = "repair_required"
    elif counts["revise_plan"] or findings:
        status = "repair_required"
    elif counts["pass_with_caveat"] or counts["defer"]:
        status = "verification_ready_with_caveats"
    else:
        status = "verification_ready"
    overlay: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "overlay_id": _stable_id(
            "overlay",
            {"base_plan_digest": base_plan_digest, "context_digest": context["digest"]},
        ),
        "base_plan_digest": base_plan_digest,
        "computed_base_plan_digest": computed_plan_digest,
        "base_plan_digest_preserved": plan_digest_valid,
        "status": status,
        "semantics": "verification readiness of a plan; not validation of executed evidence",
        "verification_context": {
            key: value for key, value in context.items() if key != "inputs"
        },
        "claim_atoms": claims,
        "evidence_atoms": evidence,
        "computation_atoms": sorted(
            computations, key=lambda row: row["computation_id"]
        ),
        "derivation_edges": sorted(derivation_edges, key=lambda row: row["edge_id"]),
        "symbolic_constraint_contracts": sorted(
            symbolic_constraint_contracts, key=lambda row: row["contract_id"]
        ),
        "deterministic_adapter_contracts": deterministic_adapter_contracts,
        "authority_profiles": sorted(
            authority_profiles, key=lambda row: row["profile_id"]
        ),
        "uncertainty_vectors": sorted(
            uncertainty_vectors, key=lambda row: row["claim_id"]
        ),
        "evidence_independence_clusters": evidence_clusters,
        "generative_envelopes": sorted(
            generative_envelopes, key=lambda row: row["claim_id"]
        ),
        "risk_and_exploration_policy": {
            "severity_basis": [
                "materiality",
                "decision impact",
                "irreversibility",
                "claim strength",
                "evidence gap",
            ],
            "exploratory_template": "preserve a labeled hypothesis with provenance, rivals, uncertainty, a discriminating test, and prohibited factual promotion",
            "confirmatory_template": "require closed grounding, applicable authority, method diagnostics, contradiction handling, and claim-ceiling compliance",
            "citation_exemptions": [
                "user constraints",
                "planned future actions",
                "deterministic transformations",
                "explicit placeholders",
                "declared unknowns",
                "properly labeled hypotheses",
            ],
            "failure_propagation": "local to affected claims and transitive dependents",
            "search_stop_rule": "stop when predicates are supported, unresolved, contradicted, or the frozen budget is exhausted",
        },
        "method_assignments": sorted(
            method_assignments, key=lambda row: row["claim_id"]
        ),
        "verification_obligations": sorted(
            obligations, key=lambda row: row["obligation_id"]
        ),
        "grounding_matrix": sorted(matrix, key=lambda row: row["claim_id"]),
        "deterministic_checks": sorted(
            deterministic_checks, key=lambda row: row["check_id"]
        ),
        "findings": sorted(findings, key=lambda row: str(row["finding_id"])),
        "verification_test_specifications": sorted(
            tests, key=lambda row: row["check_id"]
        ),
        "proposed_repairs": sorted(repairs, key=lambda row: row["repair_id"]),
        "local_disposition_counts": {
            key: counts[key]
            for key in (
                "pass",
                "pass_with_caveat",
                "defer",
                "revise_plan",
                "block",
                "inconclusive",
            )
        },
        "reused_responsibilities": sorted(
            set(_REUSE_OWNER.values())
            | {
                "source-result-fidelity-verifier",
                "retrieval-schema-validator",
                "evidence-sufficiency-gate",
                "formal-symbol-grounding-linker",
                "claim-ceiling-propagator",
            }
        ),
        "route_only": True,
        "network_performed": False,
        "retrieval_performed": False,
        "execution_performed": False,
        "store_mutation_performed": False,
        "base_plan_mutation_performed": False,
    }
    overlay["summary_event"] = build_verification_summary_event(overlay)
    return _seal(overlay)


def selectively_invalidate_verification(
    overlay: Mapping[str, Any], changed_dependencies: Iterable[str]
) -> dict[str, Any]:
    """Return a local, transitive invalidation receipt without editing a sidecar."""

    changes = sorted({str(value) for value in changed_dependencies})
    obligations = [dict(row) for row in overlay.get("verification_obligations", ())]
    invalid_claims: set[str] = set()
    invalid_obligations: set[str] = set()
    if "base_plan_digest" in changes or str(overlay.get("base_plan_digest")) in changes:
        invalid_obligations = {str(row["obligation_id"]) for row in obligations}
        invalid_claims = {str(row["claim_id"]) for row in obligations}
    else:
        for row in obligations:
            if set(map(str, row.get("invalidation_inputs", ()))) & set(changes):
                invalid_obligations.add(str(row["obligation_id"]))
                invalid_claims.add(str(row["claim_id"]))
    edges = [dict(row) for row in overlay.get("derivation_edges", ())]
    changed = True
    while changed:
        changed = False
        for edge in edges:
            if (
                set(map(str, edge.get("input_claim_ids", ()))) & invalid_claims
                and str(edge.get("output_claim_id")) not in invalid_claims
            ):
                invalid_claims.add(str(edge["output_claim_id"]))
                changed = True
    for row in obligations:
        if str(row.get("claim_id")) in invalid_claims:
            invalid_obligations.add(str(row["obligation_id"]))
    invalid_findings = {
        str(row.get("finding_id"))
        for row in overlay.get("findings", ())
        if str(row.get("claim_id")) in invalid_claims
    }
    retained = [
        str(row.get("digest") or _digest(row))
        for row in overlay.get("findings", ())
        if str(row.get("finding_id")) not in invalid_findings
    ]
    return _seal(
        {
            "schema_version": INVALIDATION_SCHEMA,
            "base_overlay_digest": str(overlay.get("digest", "")),
            "changed_dependencies": changes,
            "invalidated_claim_ids": sorted(invalid_claims),
            "invalidated_obligation_ids": sorted(invalid_obligations),
            "invalidated_finding_ids": sorted(invalid_findings),
            "retained_finding_digests": sorted(retained),
            "recomputation_required": bool(invalid_claims),
            "local_and_transitive": True,
        }
    )


def build_verification_summary_event(overlay: Mapping[str, Any]) -> dict[str, Any]:
    """Render a normalized user-facing event, never hidden chain-of-thought."""

    counts = dict(overlay.get("local_disposition_counts", {}))
    affected = sorted(
        {
            str(row.get("target"))
            for row in overlay.get("findings", ())
            if row.get("target")
        }
    )
    return {
        "schema_version": SUMMARY_EVENT_SCHEMA,
        "stage": "post-plan evidence and determinism verification",
        "status": str(overlay.get("status", "building")),
        "action": "Checked the immutable plan for typed claims, evidence paths, method fit, authority, provenance closure, and claim ceilings.",
        "rationale_summary": "Exact checks were preferred where semantics were fully specified; bounded semantic and exploratory methods remain available where exact checks are inadequate.",
        "checked": [
            "base plan digest",
            "typed graph",
            "claim decomposition",
            "method assignments",
            "source policy",
            "grounding and claim ceilings",
        ],
        "local_disposition_counts": counts,
        "affected_plan_locations": affected,
        "remaining_uncertainty": "Planned evidence and computations are not treated as executed or validated.",
        "next_action": (
            "Apply only the proposed local repairs through the existing versioned refinement lifecycle."
            if affected
            else "Retain the sidecar and verify actual artifacts after controlled execution."
        ),
        "hidden_reasoning_exposed": False,
        "evidence_validated": False,
    }
