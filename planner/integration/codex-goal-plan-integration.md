<!--
SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>

SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
Neuro-symbolic AI Group

SPDX-License-Identifier: Apache-2.0
-->
# Codex goal and plan integration

## Purpose

The planner can project an accepted research objective and its current
execution progress into Codex's goal and plan functions. This makes long-running
work visible and resumable in the agent interface without creating a second
source of planning truth.

The planner's versioned plan bundle, TODO graph, hooks, acceptance record, and
closure evidence remain canonical. A Codex goal is a durable thread-level
objective binding. A Codex plan is a concise progress projection of the current
planner version, not the full TODO ledger. Codex state may reveal drift or an
external terminal transition, but it never silently rewrites planner evidence.

## Capability and authority boundary

`CodexControlPlaneAdapter` is a deterministic runtime service, not a skill. At
run start and resume it records which goal and plan functions are available,
their observed contract version or digest, and supported operations. An absent
or incompatible function produces an explicit `local_only` result; the planner
continues from its persisted state when the requested outcome does not require
Codex synchronization.

Goal creation is authority-sensitive:

- the adapter may create a Codex goal only when the user explicitly asks to
  establish or pursue a durable goal;
- it never infers goal-creation permission from a complex request, an execute
  mode, or the presence of a planner plan;
- a token budget is supplied only when the user explicitly specifies it;
- the adapter checks current goal state before creation and never replaces an
  unfinished goal implicitly; and
- binding an existing goal requires resolvable thread/goal identity and an
  objective-compatible, authority-valid planner run.

Plan projection can be enabled for a complex active planner run when the Codex
plan capability is available. It exposes milestones, not internal scratch work
or every atomic TODO. It carries no new execution authority.

## State mapping

### Goal binding

`codex-goal-binding.json` records the planner run and plan version, Codex
thread/goal identity, normalized objective and digest, creation authority,
explicit budget provenance when present, observed state, last reconciliation,
and one of `unbound`, `active`, `complete`, `blocked`, `unavailable`, or
`drifted`.

The normalized goal objective is derived from the accepted user need and
outcome contract. It must describe the durable outcome, not a conjectured
architecture or a transient implementation step.

The adapter reads goal state at initial binding, resume, before a terminal
update, and during explicit reconciliation. It marks a Codex goal complete only
after planner closure proves that all mandatory hooks, TODOs, criteria, tests,
provenance, and release invariants are satisfied. It reports any required final
budget usage returned by the goal capability. It marks a goal blocked only
when the Codex goal contract's repeated-blocker threshold is met and the planner
has reached a genuine impasse; a single blocked hook, missing optional input,
or ordinary incomplete work is insufficient. Pause, resume, or budget mutation
is never simulated through a terminal goal update.

### Plan projection

`codex-plan-projection.json` maps stable planner milestone IDs to Codex plan
steps and `pending`, `in_progress`, or `completed` status. It obeys these rules:

- use a small outcome-oriented milestone set derived from the current profile,
  plan version, and dependency graph;
- allow at most one `in_progress` step;
- calculate status from current canonical hook/TODO evidence, never from prose
  or from the prior Codex projection;
- update at route resolution, plan acceptance, implementation/rerun milestones,
  material replanning, terminal blockage, and closure rather than on every
  atomic event;
- create a new projection revision when the planner plan version changes and
  retain the superseded mapping; and
- leave no pending or in-progress step when the corresponding planner run is
  validly closed.

## Synchronization and reconciliation

Every control-plane operation uses a stable idempotency key derived from run,
plan version, operation, and payload digest and appends a redacted event to
`events/codex-sync-events.jsonl`. `codex-reconciliation.json` compares the
expected planner projection with observed Codex state and classifies it as
`aligned`, `local_only`, `stale_projection`, `objective_mismatch`,
`terminal_conflict`, `unavailable`, or `error`.

Reconciliation is deliberately asymmetric:

1. accepted planner state determines the desired goal/plan projection;
2. Codex reads establish what is currently visible in the thread;
3. mismatches become explicit evidence and a next action; and
4. no mismatch mutates the planner objective, TODO state, hook state, or
   closure decision automatically.

Retries with the same payload are no-ops; conflicting payloads under the same
idempotency key fail closed. A new thread or lost goal binding is not guessed
from text similarity. Resume can remain `local_only`, request an authorized
rebind, or create a newly requested goal while preserving the old binding
history.

## User-visible behavior

`PlannerRunManifest` exposes Codex capability status, goal-binding status,
plan-projection revision/digest, last synchronization event, reconciliation
status, and any action needed from the user. The reasoning log explains goal or
plan synchronization decisions at the level of objective, milestone, evidence,
and consequence; it does not expose hidden chain-of-thought.

Failure to synchronize Codex state blocks closure only when the accepted plan
explicitly requires that integration. Otherwise the planner returns a clear
degraded-mode notice and preserves complete local planning, provenance, and
execution evidence.

## Required verification

Contract and integration tests must cover explicit and absent goal authority,
existing unfinished goals, optional explicit budgets, unavailable functions,
schema drift, thread changes, retries, resume, plan revision, the single-active-
step invariant, stale projections, external terminal conflicts, premature
completion/blocking attempts, true closure, and budget-usage reporting. Tests
must also prove that Codex state cannot become an alternate TODO ledger or
silently alter the accepted planner objective.
