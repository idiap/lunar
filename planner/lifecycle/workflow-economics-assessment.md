<!--
SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>

SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
Neuro-symbolic AI Group

SPDX-License-Identifier: Apache-2.0
-->
# Workflow economics assessment lifecycle

Workflow economics is an optional, default-off planner sidecar. It estimates
human-equivalent effort and direct execution resources without changing the
scientific plan, route, quality contract, answer-trust controls, execution
authority, or release decision.

## Prospective lifecycle

1. Seal the workflow plan and scientific acceptance criteria.
2. Freeze an output-equivalent traditional `ComparatorContract`.
3. Compile the stage DAG into non-overlapping work units.
4. Resolve observed, benchmarked, calibrated, expert, or generic driver
   evidence without filling unknowns with zero.
5. Calculate manual and assisted human-effort distributions, including review,
   correction, approval, rework, and integration.
6. Calculate prospective token and non-LLM resource distributions from explicit
   invocation, context, output, retry, cache, and tool assumptions.
7. Emit prospective effort/resource artifacts and a clearly labeled card.
8. Optionally reserve a P90 direct-cost envelope only under separate budget
   authority.

Prospective artifacts are plans, not observations. They cannot claim that a
source was read, a task executed, a token consumed, or money spent.

## Retrospective lifecycle

1. Receive an exact run digest, retrospective provenance, human-review
   observations, provider/runtime usage receipts, and effective price-book
   digest through an authorized host boundary.
2. Reconcile observed work without upgrading missing stages to executed.
3. Calculate assisted human effort from authorized aggregate observations and
   retain the original prospective estimate.
4. Normalize provider token semantics without double counting cached,
   reasoning, output, tool-context, failed, or retried consumption.
5. Price each supported line with the snapshot effective at event time.
6. Preserve unsupported quantities and prices as `not_reported` or
   `not_calculable`; never zero-fill.
7. Reconcile reservations, observed-not-invoiced spend, and later invoice lines
   idempotently.
8. Emit retrospective artifacts through an explicit `ArtifactStore` write.

## Artifact placement

Authorized persistent artifacts use:

```text
artifacts/runs/planner/<plan-id>/workflow-economics/
  effort-estimate-<digest>.json
  resource-estimate-<digest>.json
  effort-assessment-<digest>.json
  resource-usage-<digest>.json
  cost-reconciliation-<digest>.json
  economics-report-<digest>.json
```

Budget state, when separately enabled, is host-owned and follows confined,
atomic CostGuard-compatible paths. The planner never persists implicitly.

## Invalidation

| Changed input | Invalidated result |
|---|---|
| Workflow, acceptance contract, workload, comparator, or effort policy | Prospective and retrospective effort; prospective resources |
| Run or human-review observations | Retrospective effort only |
| Provider usage or accounting-semantics adapter | Resource usage and cost |
| Price book | Cost only; observed tokens remain unchanged |
| FX snapshot | Converted presentation only |

Every artifact retains exact input, policy, calibration, adapter, price, seed,
and digest bindings so unchanged portions can replay independently.

## User communication

Lead with the comparator and uncertainty range. Show manual-equivalent effort,
assisted residual effort, net savings (including negative savings), and the
dominant uncertainty drivers. Then show token/resource classes, evidence-state
coverage, priced and unpriced cost subtotals, and shared/unallocated overhead.
State that the report is a workflow-planning estimate, not employee
productivity telemetry or scientific-quality evidence.

## Rollout

Rollout is `off -> fixture -> shadow -> audit -> advisory`, with rollback to
`off`. Synthetic fixtures prove mechanics only. Advisory promotion requires
held-out output-equivalent expert calibration, exact complete-fixture cost
replay, zero polarity and missing-as-zero escapes, privacy checks, and default-
off compatibility. Budget enforcement is separate and cannot affect scientific
validity.
