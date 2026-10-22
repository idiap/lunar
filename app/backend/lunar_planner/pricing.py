# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0

"""Immutable effective-time price books and exact workflow cost arithmetic.

Purpose: provide the `pricing` implementation within `Lunar planner`. Key concepts: explicit responsibility, typed interfaces, and reproducible behavior. Principal I/O and failure semantics are defined by the public callables below.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_EVEN, ROUND_HALF_UP
from typing import Any, Mapping, Sequence

from .portable import stable_hash


class PricingError(ValueError):
    """Raised for ambiguous or internally inconsistent price data."""


_ROUNDING = {
    "ceiling": ROUND_CEILING,
    "half_even": ROUND_HALF_EVEN,
    "half_up": ROUND_HALF_UP,
}


def _time(value: object) -> datetime:
    """Time."""
    text = str(value)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PricingError(f"invalid timestamp: {value!r}") from exc
    if parsed.tzinfo is None:
        raise PricingError("timestamps must include a timezone")
    return parsed.astimezone(timezone.utc)


def seal_price_book(price_book: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and content-address a price-book snapshot."""

    book = deepcopy(dict(price_book))
    supplied = book.pop("digest", None)
    if book.get("schema_version") != "lunar.planner.price-book/v1":
        raise PricingError("unsupported price-book schema_version")
    if not isinstance(book.get("rates"), list) or not book["rates"]:
        raise PricingError("price book requires rates")
    identities: set[tuple[Any, ...]] = set()
    for rate in book["rates"]:
        for key in (
            "provider",
            "service",
            "region",
            "tier",
            "resource_class",
            "unit",
            "currency",
            "effective_from",
            "rate_nano",
            "rate_unit",
        ):
            if key not in rate:
                raise PricingError(f"rate missing {key}")
        if not isinstance(rate["rate_nano"], int) or rate["rate_nano"] < 0:
            raise PricingError("rate_nano must be a nonnegative integer")
        if not isinstance(rate["rate_unit"], int) or rate["rate_unit"] <= 0:
            raise PricingError("rate_unit must be a positive integer")
        start = _time(rate["effective_from"])
        end = _time(rate["effective_to"]) if rate.get("effective_to") else None
        if end is not None and end <= start:
            raise PricingError("effective_to must follow effective_from")
        identity = tuple(
            rate[key]
            for key in (
                "provider",
                "service",
                "region",
                "tier",
                "resource_class",
                "unit",
                "currency",
                "effective_from",
            )
        )
        if identity in identities:
            raise PricingError("duplicate price rate identity")
        identities.add(identity)
    digest = stable_hash(book)
    if supplied is not None and supplied != digest:
        raise PricingError("price-book digest mismatch")
    book["digest"] = digest
    return book


def resolve_rate(
    price_book: Mapping[str, Any],
    *,
    provider: str,
    service: str,
    region: str,
    tier: str,
    resource_class: str,
    unit: str,
    currency: str,
    timestamp: str,
) -> dict[str, Any] | None:
    """Resolve the one historical rate effective for an observed event."""

    book = seal_price_book(price_book)
    at = _time(timestamp)
    candidates = []
    for rate in book["rates"]:
        if any(
            str(rate[key]) != expected
            for key, expected in (
                ("provider", provider),
                ("service", service),
                ("region", region),
                ("tier", tier),
                ("resource_class", resource_class),
                ("unit", unit),
                ("currency", currency),
            )
        ):
            continue
        if _time(rate["effective_from"]) <= at and (
            not rate.get("effective_to") or at < _time(rate["effective_to"])
        ):
            candidates.append(rate)
    if len(candidates) > 1:
        raise PricingError("overlapping effective price rates")
    return deepcopy(candidates[0]) if candidates else None


def _rounded_nano(quantity: object, rate: Mapping[str, Any]) -> int:
    """Rounded nano."""
    if not isinstance(quantity, (int, float, Decimal)) or isinstance(quantity, bool):
        raise PricingError("usage quantity must be numeric")
    q = Decimal(str(quantity))
    if q < 0:
        raise PricingError("usage quantity must be nonnegative")
    exact = q * Decimal(rate["rate_nano"]) / Decimal(rate["rate_unit"])
    rounding = str(rate.get("rounding", "half_even"))
    if rounding not in _ROUNDING:
        raise PricingError(f"unsupported rounding rule: {rounding}")
    return int(exact.quantize(Decimal("1"), rounding=_ROUNDING[rounding]))


def price_usage_lines(
    lines: Sequence[Mapping[str, Any]],
    price_book: Mapping[str, Any],
    *,
    currency: str,
    fx_snapshot: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Price resource lines exactly and expose unpriced cost coverage."""

    book = seal_price_book(price_book)
    priced: list[dict[str, Any]] = []
    unpriced: list[dict[str, Any]] = []
    for source in lines:
        line = deepcopy(dict(source))
        rate = resolve_rate(
            book,
            provider=str(line.get("provider", "")),
            service=str(line.get("service", "")),
            region=str(line.get("region", "")),
            tier=str(line.get("tier", "")),
            resource_class=str(line.get("resource_class", "")),
            unit=str(line.get("unit", "")),
            currency=currency,
            timestamp=str(line.get("timestamp", "")),
        )
        if rate is None:
            line["cost_state"] = "not_calculable"
            line["reason"] = "no effective matching price"
            unpriced.append(line)
            continue
        cost = _rounded_nano(line.get("quantity"), rate)
        line.update(
            cost_nano=cost,
            currency=rate["currency"],
            rate=rate,
            cost_state=line.get("evidence_state", "estimated"),
        )
        priced.append(line)
    total = sum(line["cost_nano"] for line in priced)
    result: dict[str, Any] = {
        "currency": currency,
        "price_book_digest": book["digest"],
        "priced_lines": priced,
        "unpriced_lines": unpriced,
        "priced_total_nano": total,
        "line_coverage": {
            "priced": len(priced),
            "unpriced": len(unpriced),
            "total": len(lines),
        },
        "complete": not unpriced,
    }
    if fx_snapshot is not None:
        result["converted"] = convert_nano(total, currency, fx_snapshot)
    return result


def convert_nano(
    amount_nano: int, source_currency: str, fx_snapshot: Mapping[str, Any]
) -> dict[str, Any]:
    """Convert nano-currency only through a digest-bound FX snapshot."""

    snapshot = deepcopy(dict(fx_snapshot))
    supplied = snapshot.pop("digest", None)
    digest = stable_hash(snapshot)
    if supplied != digest:
        raise PricingError("FX snapshot must carry its canonical digest")
    matches = [
        rate
        for rate in snapshot.get("rates", [])
        if rate.get("source_currency") == source_currency
    ]
    if len(matches) != 1:
        raise PricingError("FX snapshot has no unique source-currency rate")
    rate = matches[0]
    numerator = rate.get("numerator")
    denominator = rate.get("denominator")
    if (
        not isinstance(numerator, int)
        or not isinstance(denominator, int)
        or numerator <= 0
        or denominator <= 0
    ):
        raise PricingError("FX rate must be a positive integer ratio")
    converted = int(
        (Decimal(amount_nano) * Decimal(numerator) / Decimal(denominator)).quantize(
            Decimal("1"), rounding=ROUND_HALF_EVEN
        )
    )
    return {
        "amount_nano": converted,
        "currency": rate["target_currency"],
        "fx_snapshot_digest": digest,
    }
