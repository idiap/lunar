<!--
SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>

SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
Neuro-symbolic AI Group

SPDX-License-Identifier: Apache-2.0
-->
# User-facing planner reasoning log

## Purpose

During planning, end users should be able to see how their stated need is being
translated into a workflow and skill implementation plan. The planner exposes a
concise decision rationale: what it currently understands, evidence consulted,
assumptions and uncertainty, alternatives considered, decisions made, resulting
plan changes, blockers, and the next planning action.

This is not a transcript of hidden chain-of-thought. It never exposes private
scratch work, raw model prompts, latent reasoning, secrets, credentials, private
paths, or withheld validation material. It provides auditable conclusions and
their evidence at the level needed to understand, challenge, and approve the
plan.

## Artifacts

Each run maintains three related surfaces:

- `events/planning-reasoning-events.jsonl` — append-only normalized events as
  planning progresses;
- `versions/<plan_version>/planning-reasoning-log.json` — immutable structured
  snapshot for one plan version; and
- `versions/<plan_version>/planning-reasoning-log.md` — concise end-user
  projection of the same snapshot.

The `PlannerRunManifest` exposes the current log URI, digest, last event ID,
plan version, and update time. A streaming or polling client can therefore show
new reasoning events without waiting for plan acceptance.

The hook event log answers *what ran*. The TODO ledger answers *what work is
planned*. The problem-to-plan trace proves coverage. The reasoning log explains
*why the planner's current interpretation and decisions lead to that work*.
The provenance graph separately answers which declared and observed
invocations, inputs, intermediates, and validations produced an addressable
part of the returned answer. It does not substitute execution facts for
planning rationale or expose hidden reasoning.

## Event contract

Every planning stage that makes or revises a semantic decision emits one
`reasoning_log` decision record or a reasoned no-op. The deterministic
`PlannerReasoningLogProjector` validates and normalizes it into an event with:

- `event_id`, `plan_id`, `plan_version`, monotonic `sequence`, timestamp,
  stage/hook ID, owner skill, and status;
- `event_kind`: `need_interpretation`, `clarification`, `route_decision`,
  `evidence_update`, `archetype_match`, `archetype_instantiation`,
  `reuse_assessment`, `alternative_comparison`,
  `assumption_update`, `critical_question`, `discovery_success`,
  `quality_criteria`, `quality_assessment`, `scope_decision`,
  `claim_calibration`, `stop_continue_pivot`, `plan_decision`, `plan_revision`,
  `blocker`, `acceptance_readiness`, or `no_change`;
- a short title and plain-language `user_summary`;
- user facts, planner inferences, and revisable assumptions kept distinct;
- evidence artifact IDs and source anchors supporting the conclusion;
- considered alternatives with concise selection or rejection reasons;
- selected decision, confidence as a calibrated category, uncertainty and
  missing information, consequences for scope and expected output;
- affected workflow stages, skills, sources, representations, hooks, TODOs,
  criteria, tests, and plan-diff references;
- questions or user decisions needed, blockers, and next action;
- superseded event IDs and invalidation reason when the plan changes; and
- audience/redaction classification plus the source artifact digest.

Confidence uses descriptive categories such as `established`, `supported`,
`tentative`, or `underdetermined`; the projector does not invent numeric
precision. Claims without evidence anchors are labeled as assumptions or
inferences rather than facts.

## End-user projection

The Markdown projection is progressively disclosed:

1. **Current plan at a glance** — understood need, selected route, proposed
   outcome, plan status, blockers, and next action.
2. **How the plan was derived** — problem frame, workflow/archetype shortlist,
   adaptation delta, catalog reuse findings, consequential assumptions,
   critical discovery questions, alternatives,
   selected solution, target discovery-success level, and why it best fits.
3. **Implementation shape** — affected skills/workflows, sources,
   representations, dependencies, TODO groups, validation, and rollback.
4. **Assumptions and open decisions** — what remains uncertain and what input
   could materially change the plan.
5. **Revision history** — substantive changes, superseded decisions, and their
   evidence without repeating unchanged prose.

The default view is brief. Detailed evidence and artifact links remain
available on demand. The renderer uses stable artifact names and user-domain
language; internal hook or schema names appear only when they help the user
review an implementation decision.

## Production and consistency

Existing reasoning owners retain semantic responsibility for their stage-level
`reasoning_log`. The projector is deterministic infrastructure: it does not
invent rationales, choose alternatives, or repair missing evidence. A stage
output and its log event share a digest and are committed atomically.

The projector checks that:

- every claimed fact or decision points to an accepted source artifact;
- alternatives and rejection reasons agree with the solution ledger;
- selected work agrees with the problem-to-plan trace and TODO graph;
- plan status, blockers, and next action agree with hook state;
- user-visible revisions identify superseded events rather than rewriting
  history; and
- the Markdown and JSON views have the same semantic digest.

A missing or contradictory explanation blocks acceptance when the associated
decision materially affects route, scope, architecture, authority, reuse,
skill creation, dependencies, validation, or expected output. Routine
deterministic state transitions may emit a concise no-op.

## Privacy and epistemic boundaries

Before persistence and rendering, the projector removes secrets, credentials,
raw private content, unsafe local paths, hidden prompts, chain-of-thought, and
source-lane material outside the user's authority. It preserves citations to
sanitized handles and describes why an item is unavailable when that affects a
decision. Redaction must not turn an inference into an apparent fact.

The log is explanatory evidence, not new planning authority. It cannot broaden
scope, approve installation/execution, raise a scientific claim ceiling, or
replace acceptance of the underlying plan digest.
