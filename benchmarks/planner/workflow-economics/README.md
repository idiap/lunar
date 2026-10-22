<!--
SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>

SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
Neuro-symbolic AI Group

SPDX-License-Identifier: Apache-2.0
-->
# Workflow economics benchmark

This frozen development suite tests planner-level human-effort, time-savings,
token, and direct-cost accounting. It contains deterministic arithmetic,
polarity, missing-data, anti-gaming, privacy, and invalidation cases.

The cases are disclosed development fixtures. They prove implementation
mechanics but are not evidence that effort profiles are calibrated to real
biomedical teams. Advisory promotion requires the independent protocol in
[`calibration-protocol.md`](calibration-protocol.md) over a frozen held-out
corpus with output-equivalent manual and assisted work.

Required global invariants:

- the comparator has equivalent scope, quality, provenance, and review;
- negative savings and `not_estimable` remain visible;
- budgets and estimates are never observed usage;
- missing usage and prices are never zero;
- cached/reasoning/output tokens do not double count;
- retries and failed billable attempts remain included;
- price changes invalidate cost but not usage or effort; and
- economics never affects scientific routing or release.
