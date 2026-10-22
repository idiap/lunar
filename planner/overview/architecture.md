<!--
SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>

SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
Neuro-symbolic AI Group

SPDX-License-Identifier: Apache-2.0
-->
# Planner architecture

## Objective

Turn an underspecified workflow goal or an output-level complaint into a
catalog-aware, implementation-grade, persistent change plan that another agent
can execute without relying on conversation memory.

The planner has five layers:

1. **Derived navigation layer** — a static, hash-aware unified surface index
   joins exact skills, workflows, stages, artifacts, hooks, sources,
   validators, tests, and report locations. Canonical and proposed overlays are
   equally searchable but preserve different authority and execution states.
   It also indexes parameterized workflow archetypes and sub-archetypes so
   planning begins from reusable structures rather than exhaustive skill scans.
2. **Semantic planning layer** — existing catalog skills decide reuse,
   sufficiency, composition, gaps, external knowledge, decomposition, criteria,
   tests, diagnosis, and closure. When a true skill change remains, this layer
   prepares bounded domain context; it does not author skill instructions.
3. **Deterministic control layer** — the shared `HookPlan`/`HookTrace` kernel,
   versioned plan store, TODO transition rules, hashes, invalidation, and
   release readiness, including a capability-negotiated Codex goal/plan
   projection adapter.
4. **Execution evidence layer** — per-plan lineage overlays, baseline and candidate runs, test results,
   implementation reports, comparisons, reviews, and closure records under
   `artifacts/runs/planner/<plan_id>/`.
5. **Provenance layer** — a prospective component-to-responsibility map is
   frozen before execution, while append-only observed invocation and artifact
   events build a retrospective graph after execution. A deterministic query
   service answers which skills and intermediate results produced any stable
   output component and reconciles planned with observed execution.

The navigation layer also has a separately governed external-framework index.
It maps Bioconductor packages/functions/skills and Biomni tools/libraries/data
to local capability contracts without giving external content canonical catalog
authority.

## Routing

The implemented natural-language front door is the read-only
`run_planner_request()` entrypoint. It uses `catalog.integrations.planner.routing` as one legacy
retrieval input and owns a staged request frame, bounded unified retrieval,
semantic adjudication, typed binding, preflight, and sealed handoff. It
classifies exactly one primary mode:

- `direct_skill_use`
- `direct_workflow_run`
- `new_workflow`
- `extend_existing_workflow`
- `refine_output_problem`
- `catalog_maintenance`
- `capability_help`
- `resume_plan`
- `insufficient_context`
- `inspect_provenance`

Direct routes gather candidates from one content-addressed component surface.
The planner owns selection through preflight; it does not own delivery.
Framework-changing routes retain the established reuse-critical review.

The same front door supports caller-held dialogue evolution without adding a
second routing surface. Each turn emits a versioned dialogue state, semantic
requirement ledger, typed workflow draft, decision-aware elicitation packet,
and a new tamper-evident continuation. Existing single-turn staged-receipt
fields remain compatible. A workflow draft may be framing, eliciting, under
construction, ready for review, or ready for delivery; only the last state may
produce a route-locked workflow delivery handoff.

Final workflow planning produces a separate content-addressed instantiation.
This guarantees requirement coverage even when a genuine new capability is
needed: the gap appears as an unavailable, non-canonical placeholder rather
than disappearing from the DAG. The planner also produces content-based test
specifications for every such proposal, but actual skill and test-file
authoring remains behind the accepted skill-creator and implementation gates.

Execution readiness is governed by a bounded refinement cycle. The planner
generates node, handoff, terminal, failure-propagation, and proposed-skill test
specifications; a separate controlled executor returns content-addressed test
evidence. Failed evidence produces an ordered repair delta that preserves
verified nodes and tests. No workflow reaches the release gate from prose
review alone, and the third failed iteration escalates rather than looping.
The test result is evidence for diagnosis, not the refinement objective. Each
iteration first localizes the causal layer and ranks competing explanations,
then emits a minimum fix and dependency-aware invalidation/rerun set. This
keeps the cycle focused on making the instantiated workflow work rather than
merely accumulating checks.

`inspect_provenance` is a read-only route over an authorized persisted run or
result. It resolves an output component, returns prospective attribution and
observed derivation paths, and can export the available intermediate-result
bundle without rerunning or modifying the workflow.

Report-only repair is a conditional result inside `refine_output_problem`, not
an intake mode. It remains provisional until lineage and diagnosis show that
upstream artifacts and claim boundaries are correct.

## Shared lifecycle

```text
request
  -> planner intent and direct-use versus change decision
  -> domain router or mandatory meta-framework router
  -> user-need packet and implementation-independent problem frame
  -> observable outcome contract and preserved-behavior lock
  -> current catalog snapshot
  -> exact workflow then full/sub-workflow archetype retrieval and ranking
  -> residual candidate discovery for unbound or intentionally changed slots
  -> actual-body semantic reuse review
  -> external-framework capability validation and reuse audit
  -> workflow/problem-specific analysis
  -> external-knowledge decision and conditional search
  -> governed source and representation plans
  -> bounded solution and composition
  -> isolated external dependency environment specification
  -> solution-hypothesis ledger and selected alternative
  -> hook and prospective output-component provenance freeze
  -> TODO, criteria, test, and problem-to-plan trace freeze
  -> skill-creator context packet or explicit no-skill-change record
  -> explicit operator acceptance of the current plan digest
  -> guarded implementation, delegating skill files only to Codex skill-creator
  -> workflow rerun and differential validation
  -> retrospective invocation/artifact graph and planned-versus-observed reconciliation
  -> review and abductive diagnosis
  -> at most three focused repair iterations
  -> unified skill/workflow index refresh and visibility-parity gate
  -> closure
```

No implementation starts before the plan, TODO graph, hooks, success criteria,
tests, baseline requirements, authorization state, and plan acceptance agree.
The YAML profiles are complete resolved DAGs; the shared lifecycle defines
validation rules and is never merged into a profile implicitly.

## Direct-use branch

When one existing skill or workflow satisfies the request, the planner resolves
its canonical contract, binds inputs, performs availability and authority
preflight, and emits a sealed delivery handoff. A separately authorized adapter
loads only that selected target. The planner never materializes an environment,
invokes the component, or validates its native artifact.

## New-workflow branch

The new-workflow path starts from the requested scientific or operational
outcome, not from a desired tool. It:

1. resolves the workflow family and output contract;
2. retrieves exact workflows, full archetypes, and reusable sub-archetypes
   before considering skill-level composition;
3. binds the best structural candidate and records its adaptation delta;
4. reads only relevant bound or residual skill bodies and classifies every needed step as
   `direct_reuse`, `composed_reuse`, `partial_reuse`, or `no_local_match`;
5. distinguishes catalog, composition, source, representation, and true
   capability gaps;
6. ranks contract-valid paths and assigns one owner to every stage;
7. adds evidence, critic, validator, writer, and release responsibilities;
8. persists a versioned, executable DAG and TODO graph.

A new workflow is justified when stable ordered handoffs among multiple skills
must be reused, observed, invalidated, rerun, and released as one contract. A
new skill is justified only after direct reuse, composed reuse, and monotonic
extension have been rejected with evidence.

### Capability-gap classification

New and extension routes emit a content-addressed
`lunar.planner.capability-gap-plan/v1` independently of any benchmark.
Each decomposed requirement records its bounded surface search and semantic
adjudication. Covered requirements name the reused component; ambiguous ones
remain qualification questions. Only a `no_local_match` becomes a gap, typed
as `universal`, `project_specific`, `adapter`, or `workflow_local`.

In a dialogue, provisional requirements are deferred rather than promoted to
gaps. Material new facts trigger reuse assessment for the affected requirement.
If later evidence establishes existing reuse, the earlier proposal is retained
as a retracted gap with its replacement component. Every stable residual gap
also declares proposed inputs, output, content correctness criteria, invariants,
failure states, claim ceiling, and transfer expectation; these fields describe
a review target and do not create a skill.

A gap is always `proposed_unavailable`, has no catalog identity, and grants no
authoring or execution authority. Universal means a stable independently useful
contract; project-specific means repository governance; adapter means an
external system or representation boundary; workflow-local means one
composition node. Skill creation remains a later governed decision.

## Skill authoring boundary

The planner never creates or updates a canonical skill body. For an accepted
skill-changing TODO it assembles an immutable, evidence-rich context packet and
invokes the installed Codex `skill-creator` through a thin deterministic
adapter. The creator owns naming, concise instructions, progressive disclosure,
resource structure, initialization, and its bundled validation. The planner
then owns repository-specific route, hook, consumer, catalog-parity, and
forward-behavior gates. If the creator is missing or fails, the TODO blocks;
there is no planner authoring fallback. See
[Codex skill-creator context control](../lifecycle/skill-creator-control.md).

## Existing-workflow refinement branch

Refinement begins with the user-visible symptom and desired behavior. The
planner resolves the workflow, run, report region, field/table/figure, and
baseline. It then traces backward through:

```text
report surface -> rendered artifact -> transformation -> stage -> skill/hook
              -> input representation -> connector/source
```

The diagnosis retains competing hypotheses and seeks the earliest divergence.
It classifies the responsible layer as one of:

- `presentation_or_report_only`
- `artifact_transformation`
- `reasoning_skill`
- `workflow_composition`
- `source_or_connector`
- `representation_or_schema`
- `validation_contract`
- `runtime_or_configuration`
- `underdetermined`

Report-only repair is allowed only when the upstream artifact is correct, the
requested scope is explicitly presentational, and the edit cannot raise a
claim ceiling.

## Source and representation boundary

External-data planning is a governed subworkflow, not an implicit side effect.
For each needed source, record access mode, license, freshness, cache policy,
provenance fields, no-hit behavior, invalid uses, directness ceiling, adapter
route, and promotion gate.

A representation gap is not automatically a skill gap. Changes to schemas,
identifiers, ontologies, normalizers, evidence atoms, graph relations, or report
contracts first require a compatibility assessment. Confirmed gaps then receive
a separate representation-change plan with migration, validator, and
downstream-consumer obligations.

## External computational frameworks

Local skill reuse remains first. When local sufficiency is partial or false,
the planner searches a pinned, validated external capability index and reviews
actual callable or skill contracts. Bioconductor release/R compatibility and
Biomni commit, tool metadata, license, conflict, data, and sandbox requirements
are explicit. External capabilities may back an existing local skill or justify
a thin adapter; they do not automatically become local skills.

The selected path receives a complete environment specification before plan
acceptance. A deterministic installer may create a content-addressed isolated
environment only after authority gates pass. It never changes the current
project environment or user libraries and never installs from an unpinned
search result.

## Persistence and invalidation

Runtime plans would live at `artifacts/runs/planner/<plan_id>/`, with immutable plan
payloads under `versions/<plan_version>/` and execution evidence under
`iterations/<iteration_id>/`. A plan revision uses an incremented version and
retains its predecessor digest. TODO events are
append-audited. Changing an input, contract, skill, source policy, or accepted
TODO invalidates its consuming hook and every transitive dependent through the
existing hook kernel.

Codex goal and plan functions are external control-plane projections over this
state, not another authority. `CodexControlPlaneAdapter` binds an explicitly
authorized durable goal to the accepted outcome and projects a compact set of
current plan milestones. It reads Codex state to detect drift, records every
synchronization event, and never infers goal-creation or budget authority,
imports plan status as TODO evidence, or marks a goal terminal before the
planner's own closure contract permits it. See
[Codex goal and plan integration](../integration/codex-goal-plan-integration.md).

## Safety and change control

- Preserve the `source`, `validation`, `post_hoc_diagnostic`, and
  `framework_improvement` lanes. Withheld validation answers never become
  generation inputs without explicit authorization.
- External search or live-source execution requires its own authority and
  source policy.
- Existing skills, hooks, workflows, output contracts, or generated catalog
  surfaces pass current contract, consumer, regression, and release-gate review.
- New and updated skill files are authored only through Codex `skill-creator`;
  planner and generic implementation code may assemble context, invoke the
  creator, review results, and integrate catalog surfaces but may not write the
  skill body.
- Shared-skill edits require canary tests for every known consumer.
- Rollback targets the recorded change set only and never resets unrelated user
  work.
- Mandatory pending, blocked, or incomplete hooks prevent closure.

## Index authority and overlays

`selected-package://surface` contains only project-canonical
catalog contracts in its authoritative view. It also publishes a clearly
separated `design_overlay` for candidate skill contexts/proposed workflows and an optional
`environment_overlay` for installed system or user skills. Neither overlay can
authorize repository composition or execution by default. Observed run
artifacts, report selectors, and claim ceilings belong to the plan's lineage
overlay; they never mutate the static index. Generated registries and
capability maps corroborate canonical bodies and expose parity drift, but
cannot override them. The lifecycle, manifest, promotion, snapshot, and
deprecation rules are defined in
[Unified skill/workflow visibility](../lifecycle/visibility-and-promotion.md).
