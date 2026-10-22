# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0

"""Tests for Workflow economics cost core.

This module protects expected behavior for the corresponding workflow, script, or repository surface. Key concepts: regression coverage, interface stability, and output integrity.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import time

import pytest

from lunar_planner.budget_accounting import (
    BudgetAccountingError,
    BudgetExceeded,
    BudgetIntegrityError,
    BudgetLedger,
    directory_lock,
)
from lunar_planner.portable import stable_hash
from lunar_planner.pricing import (
    PricingError,
    convert_nano,
    price_usage_lines,
    resolve_rate,
    seal_price_book,
)
from lunar_planner.usage_accounting import (
    UsageAccountingError,
    aggregate_usage,
    allocate_shared_line,
    estimate_workflow_resources,
    normalize_meter_receipt,
    normalize_provider_usage,
)


def _provider_receipt(**overrides: object) -> dict[str, object]:
    """Provider receipt."""
    receipt: dict[str, object] = {
        "workflow_id": "wf",
        "component_id": "search",
        "attempt_id": "attempt-1",
        "provider": "provider",
        "model": "model",
        "timestamp": "2026-08-01T00:00:00Z",
        "status": "succeeded",
        "usage": {
            "input_tokens": 1_000,
            "cached_input_tokens": 400,
            "output_tokens": 300,
            "reasoning_tokens": 100,
            "requests": 1,
        },
    }
    receipt.update(overrides)
    return receipt


def _price_book() -> dict[str, object]:
    """Price book."""
    rates = []
    for resource, amount, unit in (
        ("input_tokens", 2_000_000_000, 1_000_000),
        ("cached_input_tokens", 500_000_000, 1_000_000),
        ("output_tokens", 8_000_000_000, 1_000_000),
        ("reasoning_tokens", 8_000_000_000, 1_000_000),
        ("api_requests", 10_000_000, 1),
    ):
        rates.append(
            {
                "provider": "provider",
                "service": "model",
                "region": "global",
                "tier": "standard",
                "resource_class": resource,
                "unit": "token" if "tokens" in resource else "request",
                "currency": "USD",
                "effective_from": "2026-01-01T00:00:00Z",
                "effective_to": "2027-01-01T00:00:00Z",
                "rate_nano": amount,
                "rate_unit": unit,
                "rounding": "half_even",
                "authority": "provider_published",
            }
        )
    return seal_price_book(
        {
            "schema_version": "lunar.planner.price-book/v1",
            "retrieved_at": "2026-08-01T00:00:00Z",
            "rates": rates,
        }
    )


def test_provider_usage_preserves_raw_and_normalizes_inclusive_counters() -> None:
    """Verify provider usage preserves raw and normalizes inclusive counters."""
    normalized = normalize_provider_usage(
        _provider_receipt(),
        {"input_includes_cached": True, "output_includes_reasoning": True},
    )
    assert normalized["raw_provider_usage"]["input_tokens"] == 1_000
    assert normalized["evidence_state"] == "provider_observed"
    assert {row["resource_class"]: row["quantity"] for row in normalized["lines"]} == {
        "input_tokens": 600,
        "cached_input_tokens": 400,
        "output_tokens": 200,
        "reasoning_tokens": 100,
        "model_requests": 1,
    }


def test_unknown_provider_semantics_fail_to_not_calculable_without_guessing() -> None:
    """Verify unknown provider semantics fail to not calculable without guessing."""
    normalized = normalize_provider_usage(_provider_receipt(), {})
    assert normalized["evidence_state"] == "not_calculable"
    assert normalized["lines"] == []
    assert len(normalized["issues"]) == 2


def test_provider_usage_rejects_content_secrets_and_patient_payloads() -> None:
    """Verify provider usage rejects content secrets and patient payloads."""
    for forbidden in (
        "prompt",
        "hidden_reasoning",
        "authorization_header",
        "patient_rows",
    ):
        receipt = _provider_receipt()
        receipt["usage"][forbidden] = "must-not-be-retained"
        with pytest.raises(UsageAccountingError, match="prohibited telemetry"):
            normalize_provider_usage(
                receipt,
                {"input_includes_cached": True, "output_includes_reasoning": True},
            )


def test_retries_and_failures_are_distinct_billable_attempts() -> None:
    """Verify retries and failures are distinct billable attempts."""
    first = normalize_provider_usage(
        _provider_receipt(status="failed", billable=True),
        {"input_includes_cached": True, "output_includes_reasoning": True},
    )
    second_receipt = _provider_receipt(attempt_id="attempt-2")
    second = normalize_provider_usage(
        second_receipt,
        {"input_includes_cached": True, "output_includes_reasoning": True},
    )
    aggregate = aggregate_usage([first, second])
    assert aggregate["attempt_count"] == 2
    assert (
        next(
            row for row in aggregate["lines"] if row["resource_class"] == "input_tokens"
        )["quantity"]
        == 1_200
    )
    with pytest.raises(UsageAccountingError, match="unique"):
        aggregate_usage([first, first])


def test_missing_usage_is_not_reported_and_budget_is_not_consumption() -> None:
    """Verify missing usage is not reported and budget is not consumption."""
    receipt = _provider_receipt(usage=None, token_budget=200_000)
    normalized = normalize_provider_usage(receipt, {})
    assert normalized["evidence_state"] == "not_reported"
    assert normalized["lines"] == []


def test_non_llm_meter_and_shared_allocation_reconcile_exactly() -> None:
    """Verify non llm meter and shared allocation reconcile exactly."""
    meter = normalize_meter_receipt(
        {
            "workflow_id": "wf",
            "component_id": "ocr",
            "attempt_id": "a",
            "timestamp": "2026-08-01T00:00:00Z",
            "resource_class": "api_requests",
            "unit": "request",
            "quantity": 3,
        }
    )
    assert meter["evidence_state"] == "meter_observed"
    allocation = allocate_shared_line({"cost_nano": 10}, ["c", "a", "b"], "equal")
    assert (
        sum(row["cost_nano"] for row in allocation["allocations"])
        + allocation["unallocated_nano"]
        == 10
    )
    assert allocation["unallocated_nano"] == 1
    assert (
        allocate_shared_line({"cost_nano": 10}, ["a", "b"], "unallocated")[
            "unallocated_nano"
        ]
        == 10
    )


def test_prospective_resource_estimate_is_explicit_deterministic_and_never_uses_budget() -> (
    None
):
    """Verify prospective resource estimate is explicit deterministic and never uses budget."""
    units = [
        {
            "id": "read",
            "resource_drivers": [
                {
                    "resource_class": "input_tokens",
                    "unit": "token",
                    "p10": 100,
                    "p50": 200,
                    "p90": 400,
                    "retry_included": True,
                }
            ],
        },
        {"id": "unknown", "token_budget": 999_999},
    ]
    first = estimate_workflow_resources({"name": "wf"}, units, seed=4)
    second = estimate_workflow_resources({"name": "wf"}, units, seed=4)
    assert first == second
    assert first["schema_version"] == "lunar.planner.workflow-resource-estimate/v1"
    assert first["lines"][1]["evidence_state"] == "not_calculable"
    assert "quantity" not in first["lines"][1]


def test_price_book_is_digest_bound_historical_and_exact() -> None:
    """Verify price book is digest bound historical and exact."""
    book = _price_book()
    assert seal_price_book(book) == book
    assert (
        resolve_rate(
            book,
            provider="provider",
            service="model",
            region="global",
            tier="standard",
            resource_class="input_tokens",
            unit="token",
            currency="USD",
            timestamp="2026-08-01T00:00:00Z",
        )["rate_nano"]
        == 2_000_000_000
    )
    assert (
        resolve_rate(
            book,
            provider="provider",
            service="model",
            region="global",
            tier="standard",
            resource_class="input_tokens",
            unit="token",
            currency="USD",
            timestamp="2028-08-01T00:00:00Z",
        )
        is None
    )
    tampered = dict(book)
    tampered["retrieved_at"] = "2026-08-02T00:00:00Z"
    with pytest.raises(PricingError, match="digest"):
        seal_price_book(tampered)


def test_price_missing_is_unpriced_not_zero_and_fx_must_be_pinned() -> None:
    """Verify price missing is unpriced not zero and fx must be pinned."""
    lines = [
        {
            "provider": "provider",
            "service": "model",
            "region": "global",
            "tier": "standard",
            "resource_class": "input_tokens",
            "unit": "token",
            "quantity": 1_000,
            "currency": "USD",
            "timestamp": "2026-08-01T00:00:00Z",
            "evidence_state": "provider_observed",
        },
        {
            "provider": "provider",
            "service": "unknown",
            "region": "global",
            "tier": "standard",
            "resource_class": "api_requests",
            "unit": "request",
            "quantity": 2,
            "currency": "USD",
            "timestamp": "2026-08-01T00:00:00Z",
        },
    ]
    result = price_usage_lines(lines, _price_book(), currency="USD")
    assert result["priced_total_nano"] == 2_000_000
    assert result["complete"] is False
    assert result["unpriced_lines"][0]["cost_state"] == "not_calculable"
    snapshot = {
        "as_of": "2026-08-01T00:00:00Z",
        "rates": [
            {
                "source_currency": "USD",
                "target_currency": "CHF",
                "numerator": 4,
                "denominator": 5,
            }
        ],
    }
    with pytest.raises(PricingError, match="digest"):
        convert_nano(10, "USD", snapshot)
    snapshot["digest"] = stable_hash(snapshot)
    assert convert_nano(10, "USD", snapshot)["amount_nano"] == 8


def test_budget_reservation_authority_limits_release_and_idempotency(
    tmp_path: Path,
) -> None:
    """Verify budget reservation authority limits release and idempotency."""
    ledger = BudgetLedger(tmp_path / "budgets", tenant_id="tenant", currency="USD")
    ledger.configure_scope("run", 1_000)
    ledger.configure_scope("provider", 800)
    with pytest.raises(BudgetAccountingError, match="authority"):
        ledger.reserve("r0", 100, ["run"], authorized=False)
    reservation = ledger.reserve("r1", 600, ["provider", "run"], authorized=True)
    assert (
        ledger.reserve("r1", 600, ["run", "provider"], authorized=True) == reservation
    )
    with pytest.raises(BudgetExceeded):
        ledger.reserve("r2", 300, ["provider"], authorized=True)
    released = ledger.release("r1", "release-1", 100)
    assert ledger.release("r1", "release-1", 100) == released
    assert ledger.snapshot()["scopes"]["run"]["reserved_nano"] == 500


def test_expiry_releases_unused_reservation(tmp_path: Path) -> None:
    """Verify expiry releases unused reservation."""
    ledger = BudgetLedger(tmp_path, tenant_id="tenant", currency="USD")
    ledger.configure_scope("run", 500)
    ledger.reserve("r", 300, ["run"], authorized=True)
    expired = ledger.expire("r", "expiry-1")
    assert expired["kind"] == "expired"
    assert ledger.snapshot()["reservations"]["r"]["status"] == "expired"
    assert ledger.snapshot()["scopes"]["run"]["reserved_nano"] == 0


def test_partial_observation_late_invoice_and_variance_are_retained(
    tmp_path: Path,
) -> None:
    """Verify partial observation late invoice and variance are retained."""
    ledger = BudgetLedger(tmp_path, tenant_id="tenant", currency="USD")
    ledger.configure_scope("workflow", 2_000)
    ledger.reserve("r", 1_000, ["workflow"], authorized=True)
    observation = ledger.reconcile_observation("r", "obs-1", 400)
    assert observation["released_nano"] == 400
    assert ledger.snapshot()["scopes"]["workflow"] == {
        "limit_nano": 2_000,
        "reserved_nano": 600,
        "observed_not_invoiced_nano": 400,
        "reconciled_nano": 0,
    }
    invoice = ledger.reconcile_invoice("obs-1", "invoice-1", 410)
    assert invoice["variance_nano"] == 10
    assert ledger.reconcile_invoice("obs-1", "invoice-1", 410) == invoice
    state = ledger.snapshot()
    assert state["scopes"]["workflow"]["observed_not_invoiced_nano"] == 0
    assert state["scopes"]["workflow"]["reconciled_nano"] == 410
    final = ledger.reconcile_observation("r", "obs-2", 50, final=True)
    assert final["released_nano"] == 600
    assert ledger.snapshot()["reservations"]["r"]["remaining_nano"] == 0


def test_concurrent_reservations_cannot_overspend(tmp_path: Path) -> None:
    """Verify concurrent reservations cannot overspend."""
    ledger = BudgetLedger(tmp_path, tenant_id="tenant", currency="USD")
    ledger.configure_scope("tenant", 1_000)

    def reserve(index: int) -> bool:
        """Reserve."""
        try:
            ledger.reserve(f"r-{index}", 300, ["tenant"], authorized=True)
            return True
        except BudgetExceeded:
            return False

    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(reserve, range(10)))
    assert sum(outcomes) == 3
    state = ledger.snapshot()
    assert state["scopes"]["tenant"]["reserved_nano"] == 900
    assert len(state["reservations"]) == 3


def test_budget_paths_and_append_only_ledger_integrity(tmp_path: Path) -> None:
    """Verify budget paths and append only ledger integrity."""
    with pytest.raises(BudgetAccountingError, match="unsafe"):
        BudgetLedger(tmp_path, tenant_id="../escape", currency="USD")
    ledger = BudgetLedger(tmp_path, tenant_id="tenant", currency="USD")
    ledger.configure_scope("run", 100)
    ledger.reserve("r", 50, ["run"], authorized=True)
    lines = ledger.ledger_path.read_text().splitlines()
    assert len(lines) == 2
    ledger.ledger_path.write_text(
        lines[0] + "\n" + lines[1].replace('"sequence":2', '"sequence":9') + "\n"
    )
    with pytest.raises(BudgetIntegrityError):
        ledger.snapshot()


def test_directory_lock_rejects_same_thread_double_acquisition(tmp_path: Path) -> None:
    """Verify directory lock rejects same thread double acquisition."""
    target = tmp_path / "scope.lockdir"
    with directory_lock(target):
        with pytest.raises(BudgetAccountingError, match="double acquisition"):
            with directory_lock(target, timeout_seconds=0.01):
                pass


def test_directory_lock_cleans_stale_lockdir(tmp_path: Path) -> None:
    """Verify directory lock cleans stale lockdir."""
    target = tmp_path / "stale.lockdir"
    target.mkdir()
    (target / "owner.json").write_text('{"token":"abandoned"}\n')
    old = time.time() - 60
    os.utime(target, (old, old))
    with directory_lock(target, timeout_seconds=0.1, stale_after_seconds=1):
        assert target.is_dir()
    assert not target.exists()
