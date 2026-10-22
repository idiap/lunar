# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0

"""Provider-neutral workflow resource usage normalization and attribution.

This module deliberately keeps usage evidence separate from budgets and prices.
It preserves raw provider receipts while producing non-overlapping quantities
that pricing code can consume without guessing provider accounting semantics.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from copy import deepcopy
from typing import Any

from .portable import stable_hash

EVIDENCE_STATES = frozenset(
    {
        "invoice_reconciled",
        "provider_observed",
        "meter_observed",
        "tokenizer_derived",
        "profile_estimated",
        "heuristic_estimated",
        "not_calculable",
        "not_reported",
    }
)
_PROHIBITED_TELEMETRY_KEYS = frozenset(
    {
        "prompt",
        "prompts",
        "response",
        "response_body",
        "output_body",
        "hidden_reasoning",
        "chain_of_thought",
        "credential",
        "credentials",
        "api_key",
        "authorization",
        "authorization_header",
        "headers",
        "patient_row",
        "patient_rows",
        "source_content",
    }
)


class UsageAccountingError(ValueError):
    """Raised when usage cannot be normalized without ambiguity."""


def _quantity(value: object, label: str) -> int:
    """Quantity."""
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise UsageAccountingError(f"{label} must be a nonnegative integer")
    return value


def _reject_private_telemetry(value: object, path: str = "usage") -> None:
    """Reject content and secret-bearing fields before preserving raw usage."""

    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).casefold().replace("-", "_")
            if normalized in _PROHIBITED_TELEMETRY_KEYS:
                raise UsageAccountingError(
                    f"prohibited telemetry field at {path}.{key}"
                )
            _reject_private_telemetry(item, f"{path}.{key}")
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for index, item in enumerate(value):
            _reject_private_telemetry(item, f"{path}[{index}]")


def normalize_provider_usage(
    receipt: Mapping[str, Any], semantics: Mapping[str, Any]
) -> dict[str, Any]:
    """Preserve a raw provider receipt and normalize its token quantities.

    ``input_includes_cached`` and ``output_includes_reasoning`` must be declared
    whenever the corresponding nested counter is present. Unknown semantics
    produce an explicit ``not_calculable`` result, never an inferred number.
    Failed or cancelled attempts remain present; ``billable`` controls whether
    their quantities are eligible for pricing.
    """

    required = (
        "workflow_id",
        "component_id",
        "attempt_id",
        "provider",
        "model",
        "timestamp",
    )
    missing = [key for key in required if not str(receipt.get(key, "")).strip()]
    if missing:
        raise UsageAccountingError(f"missing receipt identities: {', '.join(missing)}")
    status = str(receipt.get("status", "succeeded"))
    if status not in {"succeeded", "failed", "cancelled"}:
        raise UsageAccountingError("status must be succeeded, failed, or cancelled")
    usage = receipt.get("usage")
    if usage is None:
        return {
            "identity": {key: receipt[key] for key in required},
            "status": status,
            "billable": bool(receipt.get("billable", status == "succeeded")),
            "evidence_state": "not_reported",
            "raw_provider_usage": None,
            "lines": [],
            "issues": ["provider usage was not reported"],
        }
    if not isinstance(usage, Mapping):
        raise UsageAccountingError("usage must be an object")
    _reject_private_telemetry(usage)

    issues: list[str] = []
    lines: list[dict[str, Any]] = []
    input_total = _quantity(usage.get("input_tokens", 0), "input_tokens")
    cached = _quantity(usage.get("cached_input_tokens", 0), "cached_input_tokens")
    output_total = _quantity(usage.get("output_tokens", 0), "output_tokens")
    reasoning = _quantity(usage.get("reasoning_tokens", 0), "reasoning_tokens")

    if cached:
        included = semantics.get("input_includes_cached")
        if not isinstance(included, bool):
            issues.append("cached input inclusion semantics are undeclared")
        else:
            uncached = input_total - cached if included else input_total
            if uncached < 0:
                raise UsageAccountingError("cached input exceeds inclusive input total")
            lines.extend(
                [
                    {
                        "resource_class": "input_tokens",
                        "quantity": uncached,
                        "unit": "token",
                    },
                    {
                        "resource_class": "cached_input_tokens",
                        "quantity": cached,
                        "unit": "token",
                    },
                ]
            )
    else:
        lines.append(
            {"resource_class": "input_tokens", "quantity": input_total, "unit": "token"}
        )

    if reasoning:
        included = semantics.get("output_includes_reasoning")
        if not isinstance(included, bool):
            issues.append("reasoning-token inclusion semantics are undeclared")
        else:
            visible_output = output_total - reasoning if included else output_total
            if visible_output < 0:
                raise UsageAccountingError(
                    "reasoning tokens exceed inclusive output total"
                )
            lines.extend(
                [
                    {
                        "resource_class": "output_tokens",
                        "quantity": visible_output,
                        "unit": "token",
                    },
                    {
                        "resource_class": "reasoning_tokens",
                        "quantity": reasoning,
                        "unit": "token",
                    },
                ]
            )
    else:
        lines.append(
            {
                "resource_class": "output_tokens",
                "quantity": output_total,
                "unit": "token",
            }
        )

    for field, resource_class, unit in (
        ("embedding_tokens", "embedding_tokens", "token"),
        ("requests", "model_requests", "request"),
    ):
        if field in usage:
            lines.append(
                {
                    "resource_class": resource_class,
                    "quantity": _quantity(usage[field], field),
                    "unit": unit,
                }
            )

    return {
        "identity": {key: receipt[key] for key in required},
        "status": status,
        "billable": bool(receipt.get("billable", status == "succeeded")),
        "evidence_state": "not_calculable" if issues else "provider_observed",
        "raw_provider_usage": deepcopy(dict(usage)),
        "semantics": deepcopy(dict(semantics)),
        "lines": [] if issues else lines,
        "issues": issues,
    }


def normalize_meter_receipt(receipt: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize a non-LLM meter without inventing contractual prices."""

    required = (
        "workflow_id",
        "component_id",
        "attempt_id",
        "timestamp",
        "resource_class",
        "unit",
    )
    missing = [key for key in required if not str(receipt.get(key, "")).strip()]
    if missing:
        raise UsageAccountingError(f"missing meter identities: {', '.join(missing)}")
    quantity = receipt.get("quantity")
    if (
        not isinstance(quantity, (int, float))
        or isinstance(quantity, bool)
        or quantity < 0
    ):
        raise UsageAccountingError("meter quantity must be nonnegative")
    return {
        "identity": {
            key: receipt[key]
            for key in ("workflow_id", "component_id", "attempt_id", "timestamp")
        },
        "status": str(receipt.get("status", "succeeded")),
        "billable": bool(receipt.get("billable", True)),
        "evidence_state": "meter_observed",
        "raw_meter_receipt": deepcopy(dict(receipt)),
        "lines": [
            {
                "resource_class": str(receipt["resource_class"]),
                "quantity": quantity,
                "unit": str(receipt["unit"]),
            }
        ],
        "issues": [],
    }


def aggregate_usage(receipts: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Aggregate normalized attempts without promoting their evidence states."""

    totals: dict[tuple[str, str], float] = defaultdict(float)
    coverage: dict[str, int] = defaultdict(int)
    attempts: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for receipt in receipts:
        identity = receipt.get("identity", {})
        key = (
            str(identity.get("workflow_id", "")),
            str(identity.get("component_id", "")),
            str(identity.get("attempt_id", "")),
        )
        if not all(key) or key in seen:
            raise UsageAccountingError("attempt identities must be complete and unique")
        seen.add(key)
        state = str(receipt.get("evidence_state", ""))
        if state not in EVIDENCE_STATES:
            raise UsageAccountingError(f"unsupported evidence state: {state}")
        coverage[state] += 1
        attempts.append(deepcopy(dict(receipt)))
        if receipt.get("billable", True):
            for line in receipt.get("lines", []):
                totals[(str(line["resource_class"]), str(line["unit"]))] += line[
                    "quantity"
                ]
    return {
        "attempt_count": len(attempts),
        "lines": [
            {"resource_class": resource, "unit": unit, "quantity": quantity}
            for (resource, unit), quantity in sorted(totals.items())
        ],
        "evidence_state_attempt_counts": dict(sorted(coverage.items())),
        "attempts": attempts,
    }


def allocate_shared_line(
    line: Mapping[str, Any],
    component_ids: Sequence[str],
    method: str,
    *,
    weights: Mapping[str, int] | None = None,
) -> dict[str, Any]:
    """Allocate one integer-nano cost exactly, retaining any remainder."""

    amount = _quantity(line.get("cost_nano"), "cost_nano")
    components = sorted(set(component_ids))
    if method == "unallocated" or not components:
        return {"allocations": [], "unallocated_nano": amount, "method": "unallocated"}
    if method not in {
        "equal",
        "proportional_to_tokens",
        "proportional_to_runtime",
        "causal_owner",
        "direct",
    }:
        raise UsageAccountingError(f"unsupported allocation method: {method}")
    if method in {"direct", "causal_owner"}:
        if len(components) != 1:
            raise UsageAccountingError(
                f"{method} allocation requires exactly one component"
            )
        shares = {components[0]: amount}
    else:
        effective = (
            {component: 1 for component in components}
            if method == "equal"
            else {
                component: _quantity(
                    (weights or {}).get(component), f"weight for {component}"
                )
                for component in components
            }
        )
        denominator = sum(effective.values())
        if denominator <= 0:
            raise UsageAccountingError("allocation weights must have a positive sum")
        shares = {
            component: amount * weight // denominator
            for component, weight in effective.items()
        }
    allocated = sum(shares.values())
    return {
        "allocations": [
            {"component_id": component, "cost_nano": value}
            for component, value in sorted(shares.items())
        ],
        "unallocated_nano": amount - allocated,
        "method": method,
    }


def estimate_workflow_resources(
    plan: Mapping[str, Any],
    work_units: Sequence[Mapping[str, Any]],
    resource_profile: Mapping[str, Any] | None = None,
    *,
    seed: int = 0,
) -> dict[str, Any]:
    """Build a deterministic prospective resource envelope from explicit drivers.

    A work unit may provide ``resource_drivers`` entries containing
    ``resource_class``, ``unit`` and either ``p10/p50/p90`` or a ``central``
    quantity plus ``relative_uncertainty``. Absent drivers are represented as
    ``not_calculable``; configured budgets are intentionally ignored.
    """

    if not isinstance(seed, int) or isinstance(seed, bool) or seed < 0:
        raise UsageAccountingError("seed must be a nonnegative integer")
    profile = deepcopy(dict(resource_profile or {}))
    profile_defaults = profile.get("activity_defaults", {})
    rows: list[dict[str, Any]] = []
    for unit in work_units:
        unit_id = str(unit.get("work_unit_id") or unit.get("id") or "").strip()
        if not unit_id:
            raise UsageAccountingError("work unit requires a stable ID")
        drivers = unit.get("resource_drivers")
        source = "explicit_plan_driver"
        if not drivers:
            drivers = profile_defaults.get(str(unit.get("activity_class", "")), [])
            source = "profile_estimated"
        if not drivers:
            rows.append(
                {
                    "work_unit_id": unit_id,
                    "evidence_state": "not_calculable",
                    "reason": "no explicit resource driver or matched profile",
                }
            )
            continue
        for index, driver in enumerate(drivers):
            if not isinstance(driver, Mapping):
                raise UsageAccountingError("resource driver must be an object")
            if all(key in driver for key in ("p10", "p50", "p90")):
                values = [driver["p10"], driver["p50"], driver["p90"]]
            elif "central" in driver and "relative_uncertainty" in driver:
                central = float(driver["central"])
                spread = float(driver["relative_uncertainty"])
                values = [
                    max(0.0, central * (1.0 - spread)),
                    central,
                    central * (1.0 + spread),
                ]
            else:
                raise UsageAccountingError(
                    "resource driver requires p10/p50/p90 or central uncertainty"
                )
            if any(
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or value < 0
                for value in values
            ):
                raise UsageAccountingError(
                    "resource quantiles must be nonnegative numbers"
                )
            if not values[0] <= values[1] <= values[2]:
                raise UsageAccountingError("resource quantiles must be ordered")
            rows.append(
                {
                    "line_id": f"{unit_id}:resource:{index + 1}",
                    "work_unit_id": unit_id,
                    "resource_class": str(driver.get("resource_class", "unknown")),
                    "unit": str(driver.get("unit", "unknown")),
                    "p10": values[0],
                    "p50": values[1],
                    "p90": values[2],
                    "evidence_state": str(
                        driver.get(
                            "evidence_state",
                            (
                                "heuristic_estimated"
                                if source == "explicit_plan_driver"
                                else source
                            ),
                        )
                    ),
                    "assumptions": deepcopy(driver.get("assumptions", [])),
                    "retry_included": bool(driver.get("retry_included", False)),
                }
            )
    plan_digest = str(plan.get("plan_digest") or stable_hash(plan))
    return {
        "schema_version": "lunar.planner.workflow-resource-estimate/v1",
        "plan_digest": plan_digest,
        "seed": seed,
        "resource_profile_digest": stable_hash(profile) if profile else None,
        "lines": rows,
        "assumptions": [
            "quantities are prospective and are not observed consumption",
            "configured context or budget ceilings are not usage estimates",
            "failed and cancelled attempt allowances appear only when explicit in a driver",
        ],
        "estimate_digest": stable_hash(
            {
                "plan_digest": plan_digest,
                "seed": seed,
                "profile": profile,
                "lines": rows,
            }
        ),
    }
