<!--
SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>

SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
Neuro-symbolic AI Group

SPDX-License-Identifier: Apache-2.0
-->
# Planner artifact and state contracts

## Versioned plan directory

The implemented `PlannerStore` keeps a minimal append-only state surface:

```text
artifacts/runs/planner/<plan_id>/
  current-version.json
  compacted-projection.json
  .store.lock
  events/version-events.jsonl
  events/todo-events.jsonl
  events/acceptance-events.jsonl
```

Every event carries canonical payload and event hashes. Atomic replacement,
idempotency collision checks, tamper verification, symlink/traversal rejection,
privacy redaction, and lossless-evidence compaction are implemented. The richer
target artifact model below remains an extension contract rather than a claim
about files already materialized:

```text
artifacts/runs/planner/<plan_id>/versions/<plan_version>/
    request.json
    planner-intent-route.json
    user-need-packet.json
    problem-frame.json
    outcome-contract.json
    discovery-assumption-register.json
    critical-discovery-questions.json
    discovery-success-contract.json
    quality-gate-plan.json
    answer-control-readiness.json
    quality-gates/
    prospective-provenance-plan.json
    catalog-snapshot.json
    workflow-archetype-match.json
    archetype-instantiation-plan.json
    archetype-delta.json
    invocable-surface-snapshot.json
    invocable-surface-delta.json
    external-framework-index-validation.json
    external-framework-reuse-assessment.json
    candidate-inventory.json
    reuse-critical-packet.json
    lineage.json
    diagnosis.json
    source-plan.json
    representation-compatibility-assessment.json
    representation-change-plan.json
    external-framework-environment-spec.json
    skill-reuse-design-assessment.json
    skill-generative-test-manifest.json
    skill-creator-context-packet.json
    direct-invocation-plan.json
    solution-proposal.json
    solution-hypothesis-ledger.json
    plan.json
    todos.json
    problem-to-plan-trace.json
    planning-reasoning-log.json
    planning-reasoning-log.md
    hook-plan.json
    success-criteria.json
    test-strategy.json
    acceptance.json
    pre-change-monotonicity.json
    codex-capability-manifest.json
    codex-goal-binding.json
    codex-plan-projection.json
    codex-reconciliation.json
  iterations/<iteration_id>/
    baseline-manifest.json
    direct-native-result.json
    direct-output-validation.json
    direct-invocation-result.json
    implementation-report.json
    skill-creator-result.json
    skill-generative-validation-report.json
    codex-exec-events.jsonl
    skill-creator-revision-packet.json
    candidate-run-manifest.json
    workflow-change-differential-report.json
    contract-validation.json
    generative-validation.json
    implementation-review.json
    outcome-diagnosis.json
    reflection-history.json
    post-change-monotonicity.json
    catalog-refresh.json
    promotion-report.json
    visibility-parity-report.json
    external-environment-install-result.json
    closure.json
    lineage-overlay.json
    output-component-map.json
    retrospective-provenance-graph.json
    provenance-reconciliation.json
    provenance-redaction-manifest.json
    provenance-index.json
    provenance-queries/
    answer-trust-assessment.json
    answer-trust-card.json
    runs/baseline/
    runs/candidate/
```

`manifest.json` points to immutable versions and iterations; it does not
duplicate their payloads. Not-applicable artifacts require an explicit hook
no-op. Raw private artifacts remain in lane-scoped storage and are referenced
through sanitized handles.

The planning reasoning event stream is append-only and updated while planning
is active. Each immutable plan version pins a structured snapshot and a concise
Markdown projection with the same semantic digest. The run manifest exposes
their URI/digest and the last event ID so clients can stream or poll progress.
These artifacts contain evidence-backed conclusions and decision rationale, not
hidden chain-of-thought, raw prompts, secrets, or unauthorized source content.

The prospective provenance plan is immutable with the plan version and records
intended output-component responsibilities. Execution provenance events are
append-only observations. Each iteration graph, component map, reconciliation,
and redaction manifest is content-addressed and projected from those events;
none may infer an invocation merely because it appears in the plan or catalog.
Large intermediate results remain in authorized artifact storage and appear in
the graph through durable handles and digests.

Codex control-plane artifacts follow
[`planner/integration/codex-goal-plan-integration.md`](../integration/codex-goal-plan-integration.md).
They record observed function capabilities, an explicitly authorized goal
binding, a concise plan projection, and expected-versus-observed
reconciliation. The append-only synchronization stream carries idempotency and
payload digests. These artifacts cannot replace the accepted plan, TODO ledger,
hook trace, reasoning log, or closure evidence.

## Planning request and acceptance

The request records stable plan identity/version, verbatim request, normalized
objective, desired outputs, non-goals, workflow/run references, observed and
expected behavior, acceptance examples, constraints, authority, source policy,
known and missing inputs, assumptions, and user facts separated from planner
inferences. User-suggested architecture is stored separately as a required
constraint, preference, solution hypothesis, or out-of-scope suggestion; it is
never silently promoted into the objective.

The user-need packet records actor/consumer, job, current/desired state, impact,
examples/contrasts, preserved behavior, constraints, non-goals, facts,
inferences, assumptions, and material missing inputs. The problem frame records
an implementation-independent problem class, affected surface/unit, evidence,
rival interpretations, scope, causal unknowns, and clarification/continue
decision. The outcome contract records observable success, positive/negative
examples, allowed variability, preserved behavior, validation method, and stop
conditions before architecture selection.

The discovery assumption register records consequential scientific, data,
measurement, model, evidence, transport, representation, and operational
assumptions with origin, support, uncertainty, impact-if-false, sensitivity,
testability, disconfirming observation, priority, and disposition. The critical
question artifact ranks decision-changing questions by information gain,
falsifiability, novelty leverage, feasibility, orthogonality, and pivot value.
The discovery-success contract pins the targeted `learning_advance`,
`discovery_lead`, `follow_up_ready`, or `validation_ready` level together with
observable indicators, acceptable uncertainty, null/negative-result value,
claim language, user decision enabled, and stop/continue/pivot conditions.

The quality-gate plan identifies material decision points and freezes their
criteria before generation or selection. Each `quality-gates/<gate_id>/`
directory contains versioned criteria, generative probe/rubric manifest,
assessment, deterministic dependencies, evaluator configuration, evidence,
decision, and re-entry/stop record. Semantic gates default to generative
criteria; deterministic and human criteria retain explicit precedence for the
invariants and judgments they own.

The intent route records one primary and any secondary intents, candidate and
selected profiles/targets, confidence, missing inputs, requested execution mode,
authority notes, and the next owner. Direct-use runs may omit change-plan
artifacts, but still persist route, hooks, invocation, native result, validation,
wrapper, environment, and closure evidence.

Acceptance records `decision`, `operator`, `authority`, `plan_id`,
`plan_version`, `plan_digest`, `user_need_digest`, `problem_frame_digest`,
`outcome_contract_digest`, `problem_to_plan_trace_digest`,
`discovery_assumption_register_digest`,
`critical_discovery_questions_digest`, `discovery_success_contract_digest`,
`quality_gate_plan_digest`, `required_quality_assessment_digests`,
`workflow_archetype_match_digest`,
`archetype_instantiation_digest_or_noop`, `archetype_delta_digest_or_noop`,
`planning_reasoning_log_digest`,
`skill_reuse_design_digest_or_noop`,
`skill_generative_test_manifest_digest_or_noop`,
`skill_creator_context_digest_or_noop`,
`skill_creator_contract_digest_or_noop`, target and protected paths when
applicable, and `decided_at`. Any accepted input, creator context/contract, or
authority change invalidates acceptance.

The current reasoning-log snapshot must agree with the accepted need, problem,
outcome, solution ledger, problem-to-plan trace, TODO graph, hooks, criteria,
tests, blockers, and next action. A material decision with no user-facing
explanation or a stale/contradictory projection blocks acceptance.

Acceptance pins every required quality-gate criteria and assessment digest.
Criteria changes after observing the candidate create a new plan version and
invalidate the assessment; they never rewrite the accepted quality bar.

Acceptance pins the selected archetype match, instantiation, and delta. A
change to the archetype index, manifest, slot binding, protected invariant,
source lineage, or transfer evidence creates a new plan version and invalidates
all dependent reuse, gap, TODO, criterion, test, provenance, and execution
artifacts.

Acceptance also pins `prospective_provenance_plan_digest`. Closure of an
executed route pins the current `retrospective_provenance_graph_digest`,
`output_component_map_digest`, `provenance_reconciliation_digest`, and
`provenance_redaction_manifest_digest`. A plan-only or route-only result records
`retrospective_status: not_executed`; it cannot present prospective attribution
as observed execution.

## Answer provenance bundle

The contract in [`planner/governance/provenance.md`](provenance.md) uses stable output
component IDs for documents, sections, claims, structured fields, tables,
cells, figures, panels, captions, and recommendations. Prospective records map
those components to expected workflow stages and skill roles. Retrospective
records map them to exact observed invocations and retained inputs,
intermediates, evidence, validations, and rendering artifacts.

Every invocation and artifact identity includes its governing content digest.
Contribution roles distinguish producer, contributor, reviewer, validator, and
renderer; the last writer is never treated as the sole scientific owner.
Completeness is one of `complete`, `partial`, `unmapped`, `not_executed`, or
`unavailable`. Missing, expired, redacted, or unauthorized intermediate results
remain explicit omission nodes and cannot be silently bypassed.

Each `provenance-queries/<query_id>/` directory contains the request, resolved
component binding, audience-filtered `provenance-answer.json`, optional
intermediate-result export manifest, and result/redaction digests. Queries are
read-only and inherit the source, license, privacy, retention, and authority
envelope of the underlying run.

## Plan bundle

The bundle records predecessor digest, selected route and workflow family,
workflow-archetype match, selected instantiation or no-op, adaptation delta,
catalog snapshot digest, baseline/target contracts, actual-body reuse evidence,
typed composition handoffs, source and representation plans, change set and
blast radius, hooks, TODO IDs, criteria, tests, rerun policy, authorization,
external capability selections, external environment digest/install authority,
blockers, rollback, privacy policy, and deferred work.

The solution-hypothesis ledger compares meaningful direct-use, reuse,
composition, extension, source/representation, external-framework, new-workflow,
and justified skill-change alternatives against the outcome contract. The
problem-to-plan trace maps each selected stage, skill responsibility, change,
hook, criterion, test, and TODO backward to a user need, problem fact, outcome,
or necessary risk control and maps every accepted need forward to an owner and
verification artifact or explicit deferral.

The skill-reuse-design assessment is required when a TODO creates or materially
updates a skill. It records the invariant responsibility, reuse-scope tier,
variation axes, incidental versus intrinsic constraints, prospective consumers,
typed handoffs, exclusions, portability limits, abstraction and routing risks,
and near/far/negative transfer fixtures. A no-skill-change plan emits a reasoned
no-op.

The skill generative-test manifest pins the skill/baseline digests, Codex CLI
and model configuration, cases, prompts, fixtures, output schemas, rubrics,
sandbox/authority, timeout, and token/cost budget. Its validation report binds
every JSONL event stream and structured result to those inputs, records paired
baseline/candidate deltas and deterministic/blind-evaluator decisions, and
distinguishes behavioral failure from infrastructure failure. Neither
infrastructure failure nor `inconclusive` satisfies promotion.

When any TODO creates or materially updates a skill, the subsequent acceptance
envelope pins the plan bundle together with the Codex skill-creator contract
digest, target location, allowed and protected paths,
`skill-creator-context-packet` digest, creator invocation policy, result
contract, and no-fallback rule. A no-skill-change plan records an explicit no-op
instead of an empty packet.

The catalog snapshot pins both canonical and design-overlay visibility. The
invocable-surface delta records added, changed, deprecated, blocked, and removed
skills and workflows separately, affected routes/consumers, and the dependency
digests that determine which planning artifacts must be invalidated.

The archetype match records the normalized problem signature, bounded ranked
workflow/archetype/sub-archetype candidates, semantic fit and rejection
reasons, and the catalog/archetype digests used. The instantiation plan binds
the selected archetype's parameters and required/optional slots. The delta
classifies unchanged reuse, parameter binding, substitution, monotonic skill
extension, adapter/representation change, inserted subworkflow, removed
optional slot, and unresolved gap. Only unresolved or intentionally revised
slots expand into individual skill search.

## TODO ledger

Each TODO has `todo_id`, plan identity/version, goal, `need_ids`, `outcome_ids`,
`risk_control_ids`, `verification_artifact_ids`, one planning owner,
`execution_owner`, change type, dependencies, target surfaces,
baseline/proposed contracts, action, criteria, tests, evidence, status,
blockers, rollback, and invalidation source. Skill-file TODOs set
`execution_owner: codex-skill-creator`; non-skill integration TODOs keep their
normal repository owner. One TODO cannot mix skill authoring with integration
mutations.

```text
proposed -> accepted -> in_progress -> implemented -> verified -> closed
                         |                |             |
                         +-------------> blocked <-----+
proposed -> deferred
accepted -> deferred
```

Every transition event contains `event_id`, actor, timestamp, previous and new
status, reason, evidence digest, plan version, and idempotency key. Events are
append-only. Unblocking is recorded; revision creates a new plan version and a
supersession event rather than changing historical meaning.

## User-facing reasoning events

Each event records plan/version identity, monotonic sequence, stage/hook and
owner, event kind, user summary, separated facts/inferences/assumptions,
evidence anchors, alternatives and why-not reasons, selected decision,
calibrated confidence, uncertainty, scope/output consequences, affected
artifacts/TODOs/tests, blockers, questions, next action, supersession links,
redaction class, and source digest. Events and their originating stage artifact
are committed atomically.

The deterministic projector validates referential integrity and renders the
current-plan summary, derivation, implementation shape, assumptions/open
decisions, and revision history. It cannot invent missing rationale. Routine
state transitions may emit a reasoned no-op; missing rationale for a material
route, scope, architecture, authority, reuse, dependency, skill, validation, or
output decision blocks plan acceptance.

## Source and representation plans

Source rows include source and release IDs, access mode, license, freshness,
cache/retention policy, provenance fields, directness ceiling, invalid uses,
promotion gate, no-hit behavior, adapter route/version, identifier systems,
and status.

Representation rows include current/proposed schema and ontology versions,
identifier systems, normalization and transforms, provenance effects,
migration/versioning strategy, producer and consumer compatibility, validators,
fixtures, release sequencing, and rollback.

## External framework and environment artifacts

External index validation pins framework identity, release/commit, source
digest, completeness, license/conflict status, and staleness. Reuse assessment
maps local needs to exact external callables or skills with semantic and
representation compatibility evidence.

The environment spec records the cross-language dependency closure, platform
and resource constraints, pins, repositories, hashes, lockfile and SBOM targets,
licenses, services/data/credentials, isolation identity, install and smoke-test
commands, fallbacks, cache, and teardown. The install result records
resolved-versus-actual packages, logs, hashes, validation,
`BiocManager::valid()` when applicable, and a ready/blocked state.

## Codex skill-creator artifacts

The context packet contains accepted user intent, realistic use cases,
non-goals, actual-body reuse and gap evidence, existing contracts and consumers,
domain/source/representation constraints, candidate resource needs, authority,
tests, and repository integration obligations. It does not contain a prewritten
`SKILL.md` or copied creator instructions.

The creator result records the invoked creator contract digest, target, changed
files, resource decisions, bundled validation and script-test results,
assumptions, deviations, and unresolved issues. A revision packet contains only
observed failures, evidence, preserved intent, and the prior packet/result
digests; it returns to Codex `skill-creator` rather than authorizing planner
edits.

## Baseline, comparison, and closure

Baseline manifests pin workflow/entrypoint, exact fixture and inputs, seed,
dependency environment, source/cache versions, skill and implementation
digests, dirty-worktree/tree digest, hook trace, artifacts, report selectors,
tests, rubric, risks, and claim ceilings.

Rerun comparisons record baseline/candidate identity, input/environment
equivalence, target/intermediate/contract diffs, expected and unexpected
changes, consumer canaries, stale-output and report parity checks, claim-ceiling
comparison, deterministic tests, generative probes, regressions, acceptance,
and rollback advice.

Closure is `closed`, `closed_with_residual_risk`, `needs_refinement`, or
`blocked`. It records criteria, unresolved findings, residual risk, deferred
TODOs, final digests, post-change monotonicity, index rebuild/reassessment, and
the next allowed route.

When an iteration changes a skill, workflow, manifest, route, hook, contract,
or generated surface, closure also requires a promotion report and a
visibility-parity report. The report proves that canonical bodies and proposed
planner specifications are present at the correct authority level and that all
derived discovery views share one snapshot digest.

## Answer-trust artifacts

Answer-trust artifacts follow the lifecycle in
[`answer-trust-assessment.md`](../lifecycle/answer-trust-assessment.md).
`answer-control-readiness.json` is prospective, score-free, and bound to the
sealed plan and post-plan verification digests. It records evidence and
preservation obligations plus an attainable control band; it is never evidence
that those obligations executed.

`answer-trust-assessment.json` is retrospective and binds the exact answer,
frozen claim denominator, evidence manifest, observed provenance, applicable
quality assessments, and score-policy digest. Its claim ledger retains raw
dimension grades, gates, caps, uncertainty bounds, diagnostics, and repair
actions so every displayed number replays deterministically.
`answer-trust-card.json` is a concise projection and cannot outlive or broaden
the assessment it references.

These files are optional while the rollout state is `off`. Disabled mode does
not add placeholder artifacts or alter existing plan and result digests.
Planned-only inputs yield readiness or `not_calculable`; they never produce a
realized score. Changed answer, evidence, transformation, verifier,
reconciliation, quality, or policy digests invalidate affected assessments.

## Workflow economics artifacts

Workflow economics is default-off and keeps prospective and retrospective
polarity in separate contracts. Prospective effort/resource estimates bind the
sealed workflow, output-equivalent comparator, workload, policy, calibration,
and seed. Retrospective effort/usage/cost artifacts additionally bind the exact
run, aggregate human-review observations, provider/runtime receipts,
accounting-semantics adapter, and effective price book.

Authorized persistence uses
`artifacts/runs/planner/<plan-id>/workflow-economics/`. Missing effort, usage,
or prices remain explicit unknown/unpriced lines. Prompts, response bodies,
hidden reasoning, credentials, and patient-level rows are prohibited. A price
change invalidates cost only; it never rewrites observed tokens or effort.

## Privacy and integrity

Each run declares access mode, redaction and path-sanitization policy, retention
period, and source lane. Secrets are never persisted. Canonical hashed payloads
exclude volatile timestamps; timestamps live in manifests/events. Build IDs are
content-derived, and atomic writes plus digests protect resumption integrity.
