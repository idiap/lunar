<!--
SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>

SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
Neuro-symbolic AI Group

SPDX-License-Identifier: Apache-2.0
-->
# Planner main entrypoint

Ordinary source-explicit and source-implicit biomedical questions may route to
`external_data_query`, which returns only a dry-run source plan. Change plans
use `external_data_source_planning` after problem framing and before capability
design; see [`external-data-sources.md`](../integration/external-data-sources.md).

## Implemented route-only contract

Root `AGENTS.md` remains authoritative. The planning-only entrypoint is:

```python
run_planner_request(
    command_text: str,
    references: list[str] | None,
    authority_envelope: dict,
    execution_mode: Literal["route_only"] = "route_only",
    active_plan_id: str | None = None,
    codex_control: dict | None = None,
    supplied_inputs: dict | None = None,
    continuation: dict | None = None,
) -> dict  # compatible v1 decision containing staged-receipt/v1
```

The entrypoint owns request framing, bounded cross-kind candidate gathering,
semantic adjudication, minimum-granularity choice, typed input binding, and
preflight. It seals these stages as `lunar.planner.staged-receipt/v1` and,
when ready, returns a route-locked `lunar.planner.delivery-handoff/v1`.
The separately authorized conversational/MCP orchestrator owns delivery and
cannot change that route. Execute/plan modes and any request for network, installation,
external action, subprocess, or goal authority are denied. Persistence is an
explicit separate `PlannerStore` operation, never an entrypoint side effect.

Every public planner result also carries
`lunar.planner.next-step-guidance/v1`. The closure assessor suppresses
generic follow-ups unless the current state exposes a concrete unresolved
input, mandatory review, exact handoff acceptance, localized repair, or
capability-gap decision. When admitted, the advisor returns one action tied to
a target identifier, required input, expected artifact, observable completion
criterion, and authority boundary. This projection never executes or extends
the plan and never suggests adjacent work solely to prolong the conversation.

Every component-routing turn also emits caller-held
`lunar.planner.dialogue-state/v1`,
`lunar.planner.requirement-ledger/v1`, and
`lunar.planner.workflow-draft/v1` records inside the tamper-evident
continuation. The state links immutable turn/stage digests; distinguishes
active, superseded, and withdrawn facts; carries typed inputs without requiring
the caller to resend them; and records question history. A selected or ready
route remains refinable on the next turn. New-workflow conversations progress
through `framing`, `draft_workflow`, `ready_for_review`, and
`ready_for_delivery` rather than treating the first plausible component as a
finished composition.

When the user requests the final workflow, the receipt also contains
`lunar.planner.workflow-instantiation/v1`. It assigns every active
requirement to an existing component, a governed proposed-capability
placeholder, or an explicit unresolved blocker and records typed edges and
mapping-review needs. Each genuine proposed capability receives a
`lunar.planner.proposed-skill-test-plan/v1` with contract, missing-input,
conflict, claim-boundary, and class-specific transfer/offline tests. These are
implementation-ready test specifications; they do not claim that a skill or
test module has already been created.

The instantiation enters a bounded
`lunar.planner.workflow-refinement-cycle/v1`. The first gate checks
requirement coverage, node readiness, typed handoffs, terminal output, and test
completeness. A controlled executor may later return
`workflow_execution_results` containing per-test status and content-addressed
evidence. The planner preserves verified tests, targets the earliest failing
node or edge, and emits ordered repair actions for at most three iterations.
Release remains blocked until every required workflow and proposed-skill test
has passing evidence; the route-only planner never claims to have run them.
Diagnosis and repair are the center of this cycle: failed evidence is localized
to the earliest responsible binding, component, handoff, proposed capability,
or terminal assembly; competing causes remain visible; and the fix plan names
the minimum change, preserved verified tests, invalidated downstream tests, and
targeted rerun set. A broad rebuild is forbidden unless later evidence proves
the localized repair insufficient.

The user-facing request is problem-first. `command_text` may contain only a
need, observed problem, and desired behavior; internal skill/workflow names are
never required. References and architectural suggestions are optional. The
entrypoint preserves architectural suggestions as classified hints and routes
them into later alternative assessment rather than treating them as the plan.

`codex_control` is ignored by the route-only entrypoint. A caller may separately
project current durable state through `reconcile_control_plane`; that pure
adapter returns proposed operations and never treats remote state as scientific
input or permission to create a goal, set a budget, or broaden execution.

## Intent contract

Exactly one primary intent is selected:

| Intent | Meaning | Handoff |
|---|---|---|
| `direct_skill_use` | One existing skill can satisfy the request independently | all-skill index, `catalog.integrations.planner.routing`, semantic review, then `direct-use.yaml` |
| `direct_workflow_run` | One existing catalog workflow already fits | all-workflow index, semantic review, then `direct-use.yaml` |
| `extend_existing_workflow` | Preserve an existing workflow and add behavior | `extend-workflow.yaml` with current Lunar owners |
| `refine_output_problem` | Diagnose observed-versus-expected output behavior | `refine-workflow.yaml` with current Lunar owners |
| `new_workflow` | Stable new composition is plausibly required | `new-workflow.yaml` after reuse review |
| `catalog_maintenance` | Refresh, repair, document, or validate catalog surfaces | existing meta-framework maintenance route |
| `capability_help` | Explain available skills, workflows, stacks, or commands | deterministic invocable-function and NL-command help |
| `resume_plan` | Continue a persisted nonterminal planner run | current valid hook and plan version |
| `inspect_provenance` | Explain what was intended and what actually produced an output component | deterministic provenance query service, with semantic lineage resolution only when needed |
| `insufficient_context` | No safe primary route can be bound | persist missing inputs and stop |

Secondary intents are retained, but execution follows only the accepted primary
route. A direct-use route is preferred whenever an existing skill or workflow
can meet the requested output without changing a contract.

An explicit request to create or update a skill is a framework-changing
`catalog_maintenance` route. It must pass reuse, sufficiency, novelty,
monotonicity, TODO, criteria, and acceptance gates before the planner hands an
enriched context packet to Codex `skill-creator`. The entrypoint never authors
or patches the skill itself.

## Routing precedence

1. Resolve an explicit provenance question against an authorized persisted run
   or result without rerunning it.
2. Resume an explicitly named active plan after digest and authority checks.
3. Honor an exact existing skill/workflow request when its input contract fits.
4. Gather candidates for a concrete task from every admitted Lunar skill
   and workflow, then require complete-body semantic review.
5. Route an output complaint to refinement, not generic extension.
6. Route an explicit addition to a resolved workflow to extension.
7. Route a genuinely new stable composition to new-workflow planning only after
   reuse review.
8. Route framework/catalog changes through reuse-critical and repository
   governance review.
9. Return help or missing-input state rather than inventing a route.

Before a change profile reaches catalog-driven design, it must produce a
`user_need_packet`, implementation-independent `problem_frame`, and observable
`outcome_contract`. Clarification questions are restricted to missing facts
that could materially change scope, authority, route, causal locus, or success;
they are phrased in terms of the user's outcome rather than internal
architecture.

Names and keywords nominate candidates; final routing checks actual trigger,
input, output, authority, and non-trigger contracts. Ambiguous direct targets
remain alternatives and block execution until disambiguated.

## Completed artifact delivery

Every request receives a planning-only `delivery_package_policy`. Explicit
requests for a package, archive, downloadable bundle, generated files, or
provenance descriptors become `required_when_complete`; other requests remain
conditional and are packaged only when multiple user-facing files need to stay
together or the host explicitly opts in.

Packaging is never performed by the route-only entrypoint. After execution and
quality release, the host may call `build_delivery_package` with the completed
planner result, exact generated-file paths, and an authorized output directory.
Incomplete tasks, missing files, directories, symlinks, and duplicate paths
fail closed. A successful receipt is `ready_for_user` and exposes a ZIP path and
digest; the ZIP contains an integrity manifest, a W3C PROV descriptor for each
file, and the planner-level W3C provenance export.

For change-planning routes, discovery is workflow-first. The entrypoint asks
the selected profile to resolve exact workflows, complete archetypes, reusable
sub-archetypes, and curated composition blueprints before any portfolio-wide
skill search. An explicit workflow reference is the authoritative baseline and
suppresses incidental adjacent-workflow matches. The route-only entrypoint may
use documented semantic capability families to build a bounded shortlist, but
that shortlist is nomination evidence only: complete skill bodies and
contracts still require downstream semantic review.

Every new, extension, or refinement route emits a deterministic
`resource_scan`. It records consideration of local workflows, promoted
subworkflows, local scientific skills, Bioconductor, and Biomni; binds the scan
to the pinned local resource snapshot; and includes a content-addressed
coverage receipt. `reuse_first` remains true and
`custom_implementation_allowed` remains false until semantic reuse review has
accepted a gap. Framework dispositions distinguish selected,
considered-but-not-selected, and not-applicable surfaces without executing or
installing anything.

New and extension requests also expose `capability_gap_plan`. It decomposes the
intent, records the candidates and adjudication used to exhaust reuse, and
classifies unresolved obligations as universal, project-specific, adapter, or
workflow-local. Proposed gaps never advertise availability or authorize skill
creation.

All candidates come from the pinned unified invocable-surface snapshot. Help
may return `proposed`, `active`, `deprecated`, or `blocked` skill and workflow
rows, but execution can bind only an `active`, canonical, direct-use-eligible
surface with a validated adapter. A catalog refresh during an active run is
visible only after a new plan version accepts the refreshed snapshot.

## Direct-use behavior

Direct-use planning resolves an exact invocable surface from the canonical
catalog, binds inputs, checks sources/dependencies/authority, and returns a
route-locked delivery packet. It never executes a skill or workflow. An
authorized adapter may subsequently deliver an instruction-only advisory or
compile a planning subworkflow; that adapter and selected component own the
native result and validation.

If direct execution reveals a missing input, unavailable dependency, contract
mismatch, or output problem, it closes as blocked or offers an explicit
transition to extension/refinement. Transitioning creates a new plan version;
the direct-use run remains immutable evidence.

## Orchestrator boundaries

- `catalog.integrations.planner.routing` gathers candidates only and never selects semantically
  or executes.
- `skill-reuse-critical-reasoner` owns content-based reuse classification.
- Project skill-governance owners review contract and conversational surfaces.
- Dispatch is a separate orchestrator/adapter responsibility. Planner
  dialogue state is caller-held in a tamper-evident continuation envelope after
  every refinable turn; goal synchronization remains outside the planning-only
  profile.
- The selected skill or workflow owns its native result.
- The planner cannot silently broaden authority, modify contracts on a direct
  route, or substitute a broad router for a named specialist.

## Main output

`PlannerRunManifest` records request/route/profile identity, candidate and
selected targets, plan/version when applicable, hook trace, exact invocations,
native and wrapped artifacts, environment/source manifests, authority decisions,
blockers, transition options, status, and next action.
It also records `planning_reasoning_log_uri`,
`planning_reasoning_log_digest`, `last_reasoning_event_id`, and
`reasoning_log_updated_at`; these point to auditable decision rationale, not
hidden chain-of-thought.
It additionally exposes the current prospective provenance-plan digest,
retrospective provenance-graph digest, reconciliation status, component index,
and a stable provenance-query handle for every returned result.
For change plans it also records the workflow-archetype match, selected
instantiation or no-op, adaptation delta, residual slot IDs, and the bounded
reason for any skill-level fallback.
It records Codex control capability status, goal binding/status, plan projection
revision/digest, last synchronization event, reconciliation state, degraded-
mode reason, and required user action. These fields point to projections; the
planner bundle and TODO/hook evidence remain authoritative.
