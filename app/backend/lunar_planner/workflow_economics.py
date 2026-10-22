# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0

"""Pure human-effort and elapsed-time modelling for planner workflows.

The functions in this module operate on sealed descriptions supplied by a
caller.  They do not execute a workflow, collect telemetry, or influence
scientific routing.  In particular, machine runtime is never treated as human
labour and a prospective estimate is never presented as an observation.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any

from .config import resource_path

EFFORT_ESTIMATE_SCHEMA = "lunar.planner.workflow-effort-estimate/v1"
EFFORT_ASSESSMENT_SCHEMA = "lunar.planner.workflow-effort-assessment/v1"
EFFORT_CARD_SCHEMA = "lunar.planner.workflow-effort-card/v1"
EFFORT_INVALIDATION_SCHEMA = "lunar.planner.workflow-effort-invalidation/v1"
ECONOMICS_REPORT_SCHEMA = "lunar.planner.workflow-economics-report/v1"
RESOURCE_USAGE_SCHEMA = "lunar.planner.workflow-resource-usage/v1"
COST_RECONCILIATION_SCHEMA = "lunar.planner.workflow-cost-reconciliation/v1"
WORKFLOW_ECONOMICS_POLICY_FILE = "workflow-economics-policy-v1.json"

ACTIVITY_CLASSES = {
    "framing_protocol",
    "discovery_access",
    "screening_selection",
    "reading_interpretation",
    "extraction",
    "normalization_linkage",
    "data_staging",
    "computation_analysis",
    "consolidation_synthesis",
    "verification_critique",
    "revision_remediation",
    "coordination_governance",
    "packaging_communication",
    "cross_stage_integration",
}


class WorkflowEconomicsError(ValueError):
    """Raised when an input would make an economics result misleading."""


def load_workflow_economics_policy() -> dict[str, Any]:
    """Load and verify the packaged data-only economics policy."""

    try:
        policy = json.loads(
            resource_path("policies", WORKFLOW_ECONOMICS_POLICY_FILE).read_text(
                encoding="utf-8"
            )
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkflowEconomicsError(
            f"cannot load workflow economics policy: {exc}"
        ) from exc
    if policy.get("schema_version") != "lunar.planner.workflow-economics-policy/v1":
        raise WorkflowEconomicsError("unsupported workflow economics policy")
    supplied = policy.get("digest")
    unsigned = {key: value for key, value in policy.items() if key != "digest"}
    if supplied != _digest(unsigned):
        raise WorkflowEconomicsError("workflow economics policy digest mismatch")
    if (
        policy.get("execution_allowed") is not False
        or policy.get("dynamic_imports_allowed") is not False
    ):
        raise WorkflowEconomicsError("workflow economics policy must remain data-only")
    return policy


def resolve_workflow_economics_rollout(
    requested_state: str,
    *,
    promotion_metrics: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve a default-off advisory rollout without scientific release power."""

    policy = load_workflow_economics_policy()
    rollout = policy["rollout"]
    if requested_state not in rollout["states"]:
        raise WorkflowEconomicsError(
            f"unsupported workflow economics rollout state: {requested_state}"
        )
    blockers: list[str] = []
    if requested_state == "advisory":
        metrics = dict(promotion_metrics or {})
        gates = policy["promotion_gates"]
        minimums = {
            "effort_interval_coverage": gates["minimum_effort_interval_coverage"],
            "complete_fixture_arithmetic_replay_rate": gates[
                "complete_fixture_arithmetic_replay_rate"
            ],
            "human_reviewers": gates["minimum_human_reviewers"],
        }
        maximums = {
            "false_complete_rate": gates["maximum_false_complete_rate"],
            "false_positive_savings_rate": gates["maximum_false_positive_savings_rate"],
            "planned_as_observed_escape_count": gates[
                "planned_as_observed_escape_count"
            ],
            "budget_as_usage_escape_count": gates["budget_as_usage_escape_count"],
            "missing_as_zero_escape_count": gates["missing_as_zero_escape_count"],
            "legacy_compatibility_failure_count": gates[
                "legacy_compatibility_failure_count"
            ],
            "p95_latency_ms": gates["maximum_p95_latency_ms"],
            "mean_artifact_bytes": gates["maximum_mean_artifact_bytes"],
        }
        for name, threshold in minimums.items():
            value = metrics.get(name)
            if not isinstance(value, (int, float)) or value < threshold:
                blockers.append(f"{name} is absent or below {threshold}")
        for name, threshold in maximums.items():
            value = metrics.get(name)
            if not isinstance(value, (int, float)) or value > threshold:
                blockers.append(f"{name} is absent or above {threshold}")
    effective = (
        "audit" if requested_state == "advisory" and blockers else requested_state
    )
    return {
        "requested_state": requested_state,
        "effective_state": effective,
        "estimation_enabled": effective != "off",
        "user_visible": effective in rollout["user_visible_states"],
        "scientific_release_effect": False,
        "promotion_blockers": blockers,
        "pinned_rollback_state": rollout["pinned_rollback_state"],
        "policy_digest": policy["digest"],
    }


def _canonical(value: Any) -> str:
    """Canonical."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _digest(value: Any) -> str:
    """Digest."""
    return "sha256:" + hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _seal(value: Mapping[str, Any]) -> dict[str, Any]:
    """Seal."""
    result = deepcopy(dict(value))
    result.pop("digest", None)
    result["digest"] = _digest(result)
    return result


def _finite_nonnegative(value: Any, name: str) -> float:
    """Finite nonnegative."""
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise WorkflowEconomicsError(f"{name} must be numeric") from exc
    if not math.isfinite(number) or number < 0:
        raise WorkflowEconomicsError(f"{name} must be finite and nonnegative")
    return number


def _distribution(
    value: Any, name: str, *, allow_unknown: bool = False
) -> tuple[float, float, float] | None:
    """Distribution."""
    if value is None or value == "unknown":
        if allow_unknown:
            return None
        raise WorkflowEconomicsError(f"{name} is required; missing is not zero")
    if isinstance(value, Mapping):
        if value.get("state") == "unknown":
            return None if allow_unknown else _distribution(None, name)
        low = value.get("low", value.get("p10", value.get("minimum")))
        mode = value.get("mode", value.get("central", value.get("p50")))
        high = value.get("high", value.get("p90", value.get("maximum")))
        if low is None or mode is None or high is None:
            raise WorkflowEconomicsError(f"{name} requires low/mode/high")
        result = (
            _finite_nonnegative(low, name),
            _finite_nonnegative(mode, name),
            _finite_nonnegative(high, name),
        )
    else:
        number = _finite_nonnegative(value, name)
        result = (number, number, number)
    if not result[0] <= result[1] <= result[2]:
        raise WorkflowEconomicsError(f"{name} interval must be ordered")
    return result


def _required_distribution(value: Any, name: str) -> tuple[float, float, float]:
    """Return a required distribution with its optional type narrowed."""
    result = _distribution(value, name)
    if result is None:
        raise WorkflowEconomicsError(f"{name} is required; missing is not zero")
    return result


def validate_comparator_equivalence(comparator: Mapping[str, Any]) -> dict[str, Any]:
    """Evaluate whether a traditional comparator is output-equivalent."""

    dimensions = (
        "scope",
        "rigor",
        "evidence_coverage",
        "provenance",
        "reproducibility",
        "acceptance_tests",
        "review_posture",
    )
    missing = [name for name in dimensions if name not in comparator]
    mismatched = [
        name
        for name in dimensions
        if name in comparator
        and comparator[name] in (False, None, "different", "not_equivalent")
    ]
    practitioner = comparator.get("practitioner")
    if practitioner not in {
        "experienced",
        "experienced_practitioner",
        "declared_team_mix",
    }:
        mismatched.append("experienced_practitioner")
    ordinary_tools = comparator.get("ordinary_non_agentic_tools")
    if not isinstance(ordinary_tools, Sequence) or isinstance(
        ordinary_tools, (str, bytes)
    ):
        missing.append("ordinary_non_agentic_tools")
    status = "equivalent" if not missing and not mismatched else "not_equivalent"
    return _seal(
        {
            "schema_version": "lunar.planner.workflow-comparator-disposition/v1",
            "status": status,
            "workflow_digest": comparator.get("workflow_digest"),
            "workload_manifest_digest": comparator.get("workload_manifest_digest"),
            "missing_dimensions": sorted(set(missing)),
            "mismatched_dimensions": sorted(set(mismatched)),
            "experienced_practitioner": practitioner,
            "ordinary_non_agentic_tools": (
                list(ordinary_tools or ())
                if not isinstance(ordinary_tools, (str, bytes))
                else []
            ),
        }
    )


def compile_work_units(
    plan: Mapping[str, Any],
    workload_manifest: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Compile explicit stage activities into stable, non-overlapping work units.

    Quantities are copied only from explicit work-unit declarations.  A stage
    that merely names an activity produces an unresolved diagnostic, never a
    guessed quantity.
    """

    source = deepcopy(dict(workload_manifest or {}))
    stages = list(plan.get("stages", plan.get("workflow", {}).get("stages", ())))
    declared = list(source.get("work_units", ()))
    if not declared:
        for stage in stages:
            stage_id = str(stage.get("stage_id", stage.get("id", "")))
            for unit in stage.get("work_units", ()):
                row = deepcopy(dict(unit))
                row.setdefault("stage_id", stage_id)
                declared.append(row)
    units: list[dict[str, Any]] = []
    unresolved: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    identities: dict[str, str] = {}
    duplicate_operations: list[dict[str, str]] = []
    for index, raw in enumerate(declared):
        unit = deepcopy(dict(raw))
        stage_id = str(unit.get("stage_id", ""))
        activity = str(unit.get("activity_class", ""))
        outputs = sorted(
            map(str, unit.get("output_artifact_ids", unit.get("outputs", ())))
        )
        operation = str(unit.get("operation", activity))
        identity = str(unit.get("deduplication_key") or _digest([operation, outputs]))
        unit_id = str(
            unit.get("work_unit_id") or unit.get("id") or f"wu:{stage_id}:{index:04d}"
        )
        if not stage_id:
            unresolved.append({"work_unit_id": unit_id, "driver": "stage_id"})
        if activity not in ACTIVITY_CLASSES:
            unresolved.append({"work_unit_id": unit_id, "driver": "activity_class"})
        if "quantity" not in unit or unit.get("quantity") in (None, "unknown"):
            unresolved.append({"work_unit_id": unit_id, "driver": "quantity"})
        if not unit.get("quantity_unit"):
            unresolved.append({"work_unit_id": unit_id, "driver": "quantity_unit"})
        if not outputs:
            unresolved.append(
                {"work_unit_id": unit_id, "driver": "output_artifact_ids"}
            )
        if unit_id in seen_ids:
            raise WorkflowEconomicsError(f"duplicate work_unit_id: {unit_id}")
        seen_ids.add(unit_id)
        if identity in identities:
            duplicate_operations.append(
                {
                    "first": identities[identity],
                    "duplicate": unit_id,
                    "deduplication_key": identity,
                }
            )
        else:
            identities[identity] = unit_id
        units.append(
            {
                **unit,
                "work_unit_id": unit_id,
                "stage_id": stage_id,
                "activity_class": activity,
                "input_artifact_ids": sorted(
                    map(str, unit.get("input_artifact_ids", unit.get("inputs", ())))
                ),
                "output_artifact_ids": outputs,
                "dependencies": sorted(map(str, unit.get("dependencies", ()))),
                "multiplicity": _finite_nonnegative(
                    unit.get("multiplicity", 1), f"{unit_id}.multiplicity"
                ),
                "deduplication_key": identity,
            }
        )
    units.sort(key=lambda row: row["work_unit_id"])
    known = {row["work_unit_id"] for row in units}
    for unit in units:
        for dependency in unit["dependencies"]:
            if dependency not in known:
                unresolved.append(
                    {
                        "work_unit_id": unit["work_unit_id"],
                        "driver": f"unknown_dependency:{dependency}",
                    }
                )
    return _seal(
        {
            "schema_version": "lunar.planner.workflow-workload-inventory/v1",
            "plan_digest": plan.get("digest") or _digest(plan),
            "work_units": units,
            "unresolved_drivers": sorted(
                unresolved, key=lambda row: (row["work_unit_id"], row["driver"])
            ),
            "duplicate_operations": sorted(
                duplicate_operations, key=lambda row: row["duplicate"]
            ),
            "estimable": not unresolved and not duplicate_operations and bool(units),
        }
    )


def _sample(
    distribution: tuple[float, float, float],
    rng: random.Random,
    shared: float | None = None,
) -> float:
    """Sample."""
    low, mode, high = distribution
    if low == high:
        return low
    if shared is None:
        return rng.triangular(low, high, mode)
    split = (mode - low) / (high - low)
    if shared < split:
        return low + math.sqrt(shared * (high - low) * (mode - low))
    return high - math.sqrt((1 - shared) * (high - low) * (high - mode))


def _quantiles(values: Sequence[float]) -> dict[str, float]:
    """Quantiles."""
    ordered = sorted(values)
    if not ordered:
        raise WorkflowEconomicsError("cannot summarize an empty simulation")

    def at(q: float) -> float:
        """At."""
        position = q * (len(ordered) - 1)
        lower, upper = math.floor(position), math.ceil(position)
        if lower == upper:
            return ordered[lower]
        return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)

    return {"p10": at(0.1), "p50": at(0.5), "p90": at(0.9)}


def _critical_path(
    durations: Mapping[str, float], dependencies: Mapping[str, Sequence[str]]
) -> float:
    """Critical path."""
    visiting: set[str] = set()
    done: dict[str, float] = {}

    def visit(node: str) -> float:
        """Visit."""
        if node in done:
            return done[node]
        if node in visiting:
            raise WorkflowEconomicsError("work-unit dependency graph contains a cycle")
        visiting.add(node)
        parents = dependencies.get(node, ())
        unknown = [parent for parent in parents if parent not in durations]
        if unknown:
            raise WorkflowEconomicsError(
                f"unknown critical-path dependencies for {node}: {unknown}"
            )
        done[node] = durations[node] + max(
            (visit(parent) for parent in parents), default=0.0
        )
        visiting.remove(node)
        return done[node]

    return max((visit(node) for node in sorted(durations)), default=0.0)


def estimate_workflow_effort(
    comparator: Mapping[str, Any],
    work_units: Sequence[Mapping[str, Any]] | Mapping[str, Any],
    *,
    seed: int = 1729,
    samples: int = 2000,
    repetitions: int = 1,
    evidence_state: str = "prospective",
    observed_receipts: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Estimate manual-equivalent and assisted residual human effort.

    Each work unit supplies manual and assisted drivers independently.  Driver
    values may be scalars or ``{low, mode, high}`` triangular distributions.
    """

    if evidence_state not in {"prospective", "observed"}:
        raise WorkflowEconomicsError("evidence_state must be prospective or observed")
    if evidence_state == "observed" and observed_receipts is None:
        raise WorkflowEconomicsError(
            "observed assessments require authenticated effort receipts"
        )
    if samples < 100:
        raise WorkflowEconomicsError("at least 100 samples are required")
    if repetitions < 1:
        raise WorkflowEconomicsError("repetitions must be positive")
    disposition = validate_comparator_equivalence(comparator)
    if isinstance(work_units, Mapping):
        inventory = dict(work_units)
        rows = list(inventory.get("work_units", ()))
        inventory_digest = inventory.get("digest") or _digest(inventory)
        inventory_blockers = list(inventory.get("unresolved_drivers", ())) + list(
            inventory.get("duplicate_operations", ())
        )
    else:
        rows = list(work_units)
        inventory_digest = _digest(
            sorted(
                rows, key=lambda row: str(row.get("work_unit_id", row.get("id", "")))
            )
        )
        inventory_blockers = []
    blockers: list[str] = []
    if disposition["status"] != "equivalent":
        blockers.append("traditional comparator is not output-equivalent")
    if inventory_blockers:
        blockers.append("workload inventory has unresolved or duplicate work")
    if not rows:
        blockers.append("workload inventory is empty")
    normalized: list[dict[str, Any]] = []
    try:
        for raw in sorted(
            rows, key=lambda row: str(row.get("work_unit_id", row.get("id", "")))
        ):
            unit = deepcopy(dict(raw))
            uid = str(unit.get("work_unit_id", unit.get("id", "")))
            if not uid:
                raise WorkflowEconomicsError("every work unit requires an identity")
            quantity = _distribution(unit.get("quantity"), f"{uid}.quantity")
            multiplicity = _finite_nonnegative(
                unit.get("multiplicity", 1), f"{uid}.multiplicity"
            )
            manual = unit.get("manual", {})
            assisted = unit.get("assisted", {})
            manual_rate = _distribution(
                manual.get("rate_hours_per_unit"), f"{uid}.manual.rate"
            )
            factors = [
                _distribution(manual.get(key, 1), f"{uid}.manual.{key}")
                for key in ("complexity", "friction", "rigor")
            ]
            manual_add = [
                _required_distribution(manual.get(key, 0), f"{uid}.manual.{key}")
                for key in (
                    "setup_hours",
                    "coordination_hours",
                    "expected_rework_hours",
                )
            ]
            assisted_parts = [
                _required_distribution(assisted.get(key, 0), f"{uid}.assisted.{key}")
                for key in (
                    "human_setup_hours",
                    "work_not_automated_hours",
                    "mandatory_review_hours",
                    "approval_hours",
                    "escalation_hours",
                    "rerun_hours",
                    "coordination_hours",
                    "new_assurance_hours",
                )
            ]
            defect = _required_distribution(
                assisted.get("defect_probability", 0),
                f"{uid}.assisted.defect_probability",
            )
            correction = _required_distribution(
                assisted.get("correction_effort_hours", 0),
                f"{uid}.assisted.correction_effort",
            )
            for point in defect:
                if point > 1:
                    raise WorkflowEconomicsError(
                        f"{uid}.assisted.defect_probability must be in [0,1]"
                    )
            one_time = _required_distribution(
                unit.get("one_time_setup_hours", 0), f"{uid}.one_time_setup_hours"
            )
            waiting = _required_distribution(
                unit.get("human_waiting_hours", 0), f"{uid}.human_waiting_hours"
            )
            machine = _required_distribution(
                unit.get("machine_runtime_hours", 0), f"{uid}.machine_runtime_hours"
            )
            review_floor = _finite_nonnegative(
                unit.get("minimum_review_hours", 0), f"{uid}.minimum_review_hours"
            )
            review_index = 2
            if assisted_parts[review_index][0] < review_floor:
                raise WorkflowEconomicsError(
                    f"{uid}.mandatory_review_hours is below its declared review floor"
                )
            receipt_digest = None
            if evidence_state == "observed":
                receipt = dict((observed_receipts or {}).get(uid, {}))
                if not receipt:
                    raise WorkflowEconomicsError(
                        f"observed effort receipt is missing for {uid}"
                    )
                if receipt.get("evidence_state") not in {
                    "observed",
                    "provider_observed",
                }:
                    raise WorkflowEconomicsError(
                        f"{uid} effort receipt is not observed"
                    )
                if not receipt.get("digest"):
                    raise WorkflowEconomicsError(
                        f"{uid} observed effort receipt is not digest bound"
                    )
                observed_manual = _distribution(
                    receipt.get("manual_person_hours"),
                    f"{uid}.receipt.manual_person_hours",
                )
                observed_assisted = _distribution(
                    receipt.get("assisted_person_hours"),
                    f"{uid}.receipt.assisted_person_hours",
                )
                # Observed person-time replaces modelled human effort; runtime
                # and waiting retain separate receipt channels.
                manual_rate = (0.0, 0.0, 0.0)
                manual_add = [observed_manual, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)]
                quantity = (1.0, 1.0, 1.0)
                factors = [(1.0, 1.0, 1.0)] * 3
                assisted_parts = [observed_assisted] + [(0.0, 0.0, 0.0)] * 7
                defect = correction = (0.0, 0.0, 0.0)
                one_time = (0.0, 0.0, 0.0)
                if receipt.get("human_waiting_hours") is not None:
                    waiting = _distribution(
                        receipt["human_waiting_hours"],
                        f"{uid}.receipt.human_waiting_hours",
                    )
                if receipt.get("machine_runtime_hours") is not None:
                    machine = _distribution(
                        receipt["machine_runtime_hours"],
                        f"{uid}.receipt.machine_runtime_hours",
                    )
                receipt_digest = str(receipt["digest"])
            normalized.append(
                {
                    "unit": unit,
                    "id": uid,
                    "quantity": quantity,
                    "multiplicity": multiplicity,
                    "manual_rate": manual_rate,
                    "factors": factors,
                    "manual_add": manual_add,
                    "assisted_parts": assisted_parts,
                    "defect": defect,
                    "correction": correction,
                    "one_time": one_time,
                    "waiting": waiting,
                    "machine": machine,
                    "group": str(unit.get("correlation_group", uid)),
                    "dependencies": tuple(map(str, unit.get("dependencies", ()))),
                    "evidence_grade": str(unit.get("evidence_grade", "generic_prior")),
                    "receipt_digest": receipt_digest,
                }
            )
    except WorkflowEconomicsError as exc:
        blockers.append(str(exc))
    if blockers:
        return _seal(
            {
                "schema_version": (
                    EFFORT_ASSESSMENT_SCHEMA
                    if evidence_state == "observed"
                    else EFFORT_ESTIMATE_SCHEMA
                ),
                "status": "not_estimable",
                "evidence_state": evidence_state,
                "comparator_disposition": disposition,
                "workload_inventory_digest": inventory_digest,
                "blockers": blockers,
                "headline": None,
                "components": [],
            }
        )

    rng = random.Random(seed)
    series: dict[str, list[float]] = {
        key: []
        for key in (
            "manual",
            "assisted",
            "net",
            "gross_displaced",
            "new_assurance",
            "waiting",
            "machine",
            "manual_critical_path",
            "assisted_critical_path",
        )
    }
    per_unit: dict[str, dict[str, list[float]]] = {
        row["id"]: {"manual": [], "assisted": [], "net": []} for row in normalized
    }
    for _ in range(samples):
        shared = {row["group"]: rng.random() for row in normalized}
        manual_duration: dict[str, float] = {}
        assisted_duration: dict[str, float] = {}
        waiting_total = machine_total = assurance_total = 0.0
        for row in normalized:
            u = shared[row["group"]]
            quantity = _sample(row["quantity"], rng, u) * row["multiplicity"]
            marginal_manual = quantity * _sample(row["manual_rate"], rng, u)
            for factor in row["factors"]:
                marginal_manual *= _sample(factor, rng, u)
            manual_value = sum(_sample(part, rng, u) for part in row["manual_add"])
            manual_value += (
                marginal_manual + _sample(row["one_time"], rng, u) / repetitions
            )
            parts = [_sample(part, rng, u) for part in row["assisted_parts"]]
            assisted_value = sum(parts)
            assisted_value += _sample(row["defect"], rng, u) * _sample(
                row["correction"], rng, u
            )
            waiting_value = _sample(row["waiting"], rng, u)
            machine_value = _sample(row["machine"], rng, u)
            waiting_total += waiting_value
            machine_total += machine_value
            assurance_total += parts[-1]
            manual_duration[row["id"]] = manual_value
            # Calendar duration conservatively includes the explicitly
            # declared waiting and runtime channels while continuing to report
            # those clocks separately.
            assisted_duration[row["id"]] = (
                assisted_value + waiting_value + machine_value
            )
            per_unit[row["id"]]["manual"].append(manual_value)
            per_unit[row["id"]]["assisted"].append(assisted_value)
            per_unit[row["id"]]["net"].append(manual_value - assisted_value)
        dependencies = {row["id"]: row["dependencies"] for row in normalized}
        manual_total = sum(manual_duration.values())
        assisted_total = sum(per_unit[row["id"]]["assisted"][-1] for row in normalized)
        series["manual"].append(manual_total)
        series["assisted"].append(assisted_total)
        series["net"].append(manual_total - assisted_total)
        series["gross_displaced"].append(manual_total)
        series["new_assurance"].append(assurance_total)
        series["waiting"].append(waiting_total)
        series["machine"].append(machine_total)
        series["manual_critical_path"].append(
            _critical_path(manual_duration, dependencies)
        )
        series["assisted_critical_path"].append(
            _critical_path(assisted_duration, dependencies)
        )

    summaries = {name: _quantiles(values) for name, values in series.items()}
    manual_p50, assisted_p50 = summaries["manual"]["p50"], summaries["assisted"]["p50"]
    saving_fraction = (
        (manual_p50 - assisted_p50) / manual_p50 if manual_p50 > 0 else None
    )
    components = []
    for row in normalized:
        q = {name: _quantiles(values) for name, values in per_unit[row["id"]].items()}
        components.append(
            {
                "work_unit_id": row["id"],
                "activity_class": row["unit"].get("activity_class"),
                "manual_person_hours": q["manual"],
                "assisted_person_hours": q["assisted"],
                "net_saved_person_hours": q["net"],
                "evidence_grade": row["evidence_grade"],
                "one_time_setup_amortized_over_runs": repetitions,
                "observed_receipt_digest": row["receipt_digest"],
            }
        )
    # One-at-a-time central range supplies an interpretable, deterministic sensitivity rank.
    sensitivity = []
    for row in normalized:
        q_low, _, q_high = row["quantity"]
        r_low, _, r_high = row["manual_rate"]
        span = row["multiplicity"] * max(q_high * r_high - q_low * r_low, 0.0)
        sensitivity.append(
            {
                "work_unit_id": row["id"],
                "driver": "quantity_x_manual_rate",
                "p90_minus_p10_proxy_hours": span,
            }
        )
    sensitivity.sort(
        key=lambda item: (-item["p90_minus_p10_proxy_hours"], item["work_unit_id"])
    )
    return _seal(
        {
            "schema_version": (
                EFFORT_ASSESSMENT_SCHEMA
                if evidence_state == "observed"
                else EFFORT_ESTIMATE_SCHEMA
            ),
            "status": "estimated" if evidence_state == "prospective" else "assessed",
            "evidence_state": evidence_state,
            "seed": seed,
            "samples": samples,
            "comparator_disposition": disposition,
            "workload_inventory_digest": inventory_digest,
            "repetitions": repetitions,
            "headline": {
                "manual_person_hours": summaries["manual"],
                "assisted_person_hours": summaries["assisted"],
                "net_saved_person_hours": summaries["net"],
                "saving_fraction_at_p50": saving_fraction,
                "negative_savings": summaries["net"]["p50"] < 0,
            },
            "clocks": {
                "human_active_effort": {
                    "manual_person_hours": summaries["manual"],
                    "assisted_person_hours": summaries["assisted"],
                },
                "human_waiting_hours": summaries["waiting"],
                "machine_runtime_hours": summaries["machine"],
                "calendar_critical_path_hours": {
                    "manual": summaries["manual_critical_path"],
                    "assisted": summaries["assisted_critical_path"],
                },
            },
            "gross_work_displaced_person_hours": summaries["gross_displaced"],
            "new_assurance_work_person_hours": summaries["new_assurance"],
            "components": components,
            "sensitivity": sensitivity,
            "confidence_grade": max(
                (row["evidence_grade"] for row in normalized),
                key=lambda grade: {
                    "matched_observation": 0,
                    "frozen_benchmark": 1,
                    "matched_profile": 2,
                    "analogous_profile": 3,
                    "expert_prior": 4,
                    "generic_prior": 5,
                }.get(grade, 6),
                default="generic_prior",
            ),
            "blockers": [],
        }
    )


def build_workflow_effort_card(estimate: Mapping[str, Any]) -> dict[str, Any]:
    """Create a compact card without hiding ranges or adverse results."""
    return _seal(
        {
            "schema_version": EFFORT_CARD_SCHEMA,
            "estimate_digest": estimate.get("digest") or _digest(estimate),
            "status": estimate.get("status"),
            "evidence_state": estimate.get("evidence_state"),
            "headline": deepcopy(estimate.get("headline")),
            "clocks": deepcopy(estimate.get("clocks")),
            "top_sensitivity_drivers": deepcopy(
                list(estimate.get("sensitivity", ()))[:5]
            ),
            "component_count": len(estimate.get("components", ())),
            "caveat": "Prospective ranges are assumptions, not observed productivity or billing evidence.",
        }
    )


def invalidate_workflow_effort(
    estimate: Mapping[str, Any],
    changed_artifact_digests: Sequence[str],
    *,
    affected_work_unit_ids: Sequence[str] = (),
) -> dict[str, Any]:
    """Invalidate only components whose bound inputs changed."""
    affected = set(map(str, affected_work_unit_ids))
    invalid = sorted(
        str(row.get("work_unit_id"))
        for row in estimate.get("components", ())
        if str(row.get("work_unit_id")) in affected
    )
    return _seal(
        {
            "schema_version": EFFORT_INVALIDATION_SCHEMA,
            "estimate_digest": estimate.get("digest") or _digest(estimate),
            "changed_artifact_digests": sorted(set(map(str, changed_artifact_digests))),
            "invalidated_work_unit_ids": invalid,
            "retained_work_unit_ids": sorted(
                str(row.get("work_unit_id"))
                for row in estimate.get("components", ())
                if str(row.get("work_unit_id")) not in affected
            ),
            "headline_invalidated": bool(invalid or changed_artifact_digests),
        }
    )


def build_workflow_resource_usage(
    plan_digest: str,
    normalized_receipts: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Seal observed usage without promoting estimates or unreported values."""

    from .usage_accounting import aggregate_usage

    aggregate = aggregate_usage(normalized_receipts)
    observed = sum(
        count
        for state, count in aggregate["evidence_state_attempt_counts"].items()
        if state in {"provider_observed", "meter_observed"}
    )
    total = aggregate["attempt_count"]
    return _seal(
        {
            "schema_version": RESOURCE_USAGE_SCHEMA,
            "polarity": "observed_only",
            "plan_digest": str(plan_digest),
            "status": "observed" if total and observed == total else "partial",
            "observed_attempt_coverage": observed / total if total else None,
            "aggregate": aggregate,
            "budget_treated_as_usage": False,
        }
    )


def build_workflow_cost_reconciliation(
    resource_usage: Mapping[str, Any],
    priced_usage: Mapping[str, Any],
    *,
    reservation_digest: str | None = None,
    invoice_digest: str | None = None,
) -> dict[str, Any]:
    """Bind observed quantities to priced/unpriced lines and optional invoices."""

    if resource_usage.get("schema_version") != RESOURCE_USAGE_SCHEMA:
        raise WorkflowEconomicsError(
            "cost reconciliation requires observed resource usage"
        )
    priced = int(priced_usage.get("line_coverage", {}).get("priced", 0))
    total = int(priced_usage.get("line_coverage", {}).get("total", 0))
    return _seal(
        {
            "schema_version": COST_RECONCILIATION_SCHEMA,
            "polarity": "observed_only",
            "resource_usage_digest": resource_usage.get("digest")
            or _digest(resource_usage),
            "price_book_digest": priced_usage.get("price_book_digest"),
            "reservation_digest": reservation_digest,
            "invoice_digest": invoice_digest,
            "status": (
                "invoice_reconciled"
                if invoice_digest
                else (
                    "provider_observed_cost"
                    if priced_usage.get("complete")
                    else "partial_not_calculable"
                )
            ),
            "currency": priced_usage.get("currency"),
            "priced_total_nano": priced_usage.get("priced_total_nano"),
            "priced_lines": deepcopy(priced_usage.get("priced_lines", ())),
            "unpriced_lines": deepcopy(priced_usage.get("unpriced_lines", ())),
            "cost_line_coverage": priced / total if total else None,
            "missing_price_as_zero": False,
        }
    )


def build_workflow_economics_report(
    effort: Mapping[str, Any],
    resource: Mapping[str, Any],
    *,
    cost: Mapping[str, Any] | None = None,
    rollout_state: str = "fixture",
) -> dict[str, Any]:
    """Build a readable bundle without combining labor and direct cost as ROI."""

    rollout = resolve_workflow_economics_rollout(rollout_state)
    resource_is_partial = resource.get("status") == "partial" or any(
        row.get("evidence_state") == "not_calculable"
        for row in resource.get("lines", ())
    )
    cost_is_partial = (
        cost is not None and cost.get("status") == "partial_not_calculable"
    )
    return _seal(
        {
            "schema_version": ECONOMICS_REPORT_SCHEMA,
            "status": (
                "not_estimable"
                if effort.get("status") == "not_estimable"
                else "partial" if resource_is_partial or cost_is_partial else "complete"
            ),
            "rollout": rollout,
            "effort": deepcopy(dict(effort)),
            "resource": deepcopy(dict(resource)),
            "cost": deepcopy(dict(cost)) if cost is not None else None,
            "labor_value": None,
            "scalar_roi": None,
            "scientific_release_effect": False,
            "interpretation": (
                "Workflow-planning economics with separate human effort, elapsed time, "
                "resource usage, and direct cost; not employee productivity telemetry."
            ),
        }
    )


__all__ = [
    "ACTIVITY_CLASSES",
    "COST_RECONCILIATION_SCHEMA",
    "ECONOMICS_REPORT_SCHEMA",
    "EFFORT_ASSESSMENT_SCHEMA",
    "EFFORT_CARD_SCHEMA",
    "EFFORT_ESTIMATE_SCHEMA",
    "EFFORT_INVALIDATION_SCHEMA",
    "RESOURCE_USAGE_SCHEMA",
    "WorkflowEconomicsError",
    "build_workflow_cost_reconciliation",
    "build_workflow_economics_report",
    "build_workflow_effort_card",
    "build_workflow_resource_usage",
    "compile_work_units",
    "estimate_workflow_effort",
    "invalidate_workflow_effort",
    "load_workflow_economics_policy",
    "resolve_workflow_economics_rollout",
    "validate_comparator_equivalence",
]
