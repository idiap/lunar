<!--
SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>

SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
Neuro-symbolic AI Group

SPDX-License-Identifier: Apache-2.0
-->
# Problem-first reasoning from user need to implementation plan

## Stage ownership

The public planner owns problem framing, bounded candidate retrieval, semantic
selection or elicitation, minimum-sufficient granularity, exact input binding,
and availability/authority preflight. Its terminal planning artifact is a
sealed delivery handoff or a typed clarification, blocked, contract-gap, or
no-local-match receipt. Delivery is owned by a separately authorized
orchestrator adapter; it may not replace the selected route or repair bindings.

## User contract

The planner accepts a problem description at the user's natural level. The user
is responsible for describing what they need, what is happening now, what
should happen instead, relevant examples, constraints, and why the difference
matters. The user is not required to identify a skill, workflow, hook, data
adapter, framework, schema, or repository architecture.

If the user suggests an architectural solution, the planner preserves it
verbatim but classifies it separately as one of:

- `required_constraint` — an explicit user choice that the implementation must
  honor;
- `preference` — desirable but negotiable;
- `solution_hypothesis` — a conjecture to evaluate against the catalog and
  problem evidence; or
- `out_of_scope_suggestion` — useful context that is not part of the accepted
  need.

A suggested solution never replaces problem framing. The planner must be able
to restate the need and success condition without relying on the suggested
architecture. It may recommend a different implementation when that better
satisfies the accepted outcome and constraints, but it must explain the
tradeoff and preserve explicit user choices.

## Progressive intake

The entrypoint should first collect or infer, with visible assumptions:

- affected user or downstream consumer and the task they are trying to
  complete;
- current behavior or missing capability;
- desired behavior and observable difference;
- impact, importance, recurrence, and time sensitivity when relevant;
- concrete positive examples, negative examples, and contrasts;
- available inputs, referenced workflows/runs/outputs, and evidence anchors;
- scope, non-goals, source/data boundaries, privacy, authority, runtime, and
  compatibility constraints;
- preserved behavior that must not regress; and
- missing information whose answer could materially change the route or plan.

The planner asks only high-information, outcome-level questions. It should not
ask the user to choose among internal skills or architectures when the catalog
can resolve that choice. If missing information does not materially change the
safe plan, it proceeds with an explicit, revisable assumption. If it changes
scope, authority, success, or the responsible workflow, the planner blocks and
asks a concise question.

For multi-turn intake, the public planner reduces each new statement into an
evidence-addressed delta: `add`, `confirm`, `qualify`, `replace`, `retract`, or
`contradict`. The caller-held state retains both active and superseded values
with source turns. Retrieval consumes active requirements and current deltas,
not a flattened transcript, so a correction can invalidate a route or node
without discarding unaffected workflow work. Open questions are identified by
their decision effect and are not repeated after resolution.

## Core artifacts

### `user-need-packet.json`

Records the verbatim request, actors/consumers, job to be accomplished, current
and desired state, impact, examples/contrasts, constraints, preserved behavior,
non-goals, references, user facts, planner inferences, assumptions, ambiguity,
missing inputs, and architectural suggestions classified by the user contract.

### `problem-frame.json`

Defines the smallest defensible problem independent of implementation:

- stable problem statement and affected outcome;
- problem class: missing capability, incorrect output, incomplete output,
  inconsistent behavior, excessive effort, failed integration, source/data
  limitation, representation mismatch, validation gap, or underdetermined;
- unit of analysis/change, affected surface, context, frequency, severity, and
  reproducibility;
- evidence for the problem and rival interpretations;
- existing workflow or skill relationship when known;
- causal unknowns, scope boundary, and stop/clarification decision.

### `outcome-contract.json`

Defines success before architecture selection: observable target behavior,
positive and negative examples, acceptance signals, preserved behavior,
allowed variability, quality/evidence/claim boundaries, performance or runtime
constraints when material, validation method, and failure/stop conditions.

### `solution-hypothesis-ledger.json`

Created only after the need, problem, and outcome contract are stable. It lists
direct use, workflow reuse, composition, monotonic extension, source or
representation change, external framework reuse, new workflow, and justified
skill-change alternatives. Each alternative records evidence for/against,
typed fit, expected outcome coverage, risks, dependencies, change surface,
reversibility, user constraints, and selection/rejection reason.

User-suggested architecture appears as one alternative with its original
classification. Catalog availability alone does not make an alternative fit;
novelty alone does not make it preferable.

### `requirement-ledger.json` and `workflow-draft.json`

During conversational workflow design, every active obligation receives a
stable ID, desired output, content correctness criteria, evidence turns,
stability, dependencies, route candidates, and reuse/gap decision. The evolving
workflow draft maps these obligations to independently bound and preflighted
nodes. Edges name the artifact and required input types; an undocumented
mapping remains `requires_mapping_review` and is never invented. Corrections
revise or retire affected obligations and nodes while retaining their history.
At finalization the planner instantiates every active requirement. Existing
components retain exact bindings and preflight; genuine gaps become unavailable
placeholder nodes with proposed interfaces and test specifications; unresolved
obligations remain blockers. An instantiated graph is not called executable
while any node is unavailable or any edge still needs mapping review.

The instantiated graph is followed by a bounded refinement cycle. Static
coverage, binding, authority, handoff, terminal, and test-plan findings block
controlled execution. Later content-addressed execution results either release
the graph or identify the earliest responsible node/edge for repair while
preserving passing evidence. Three failed evidence-bearing iterations require
explicit escalation instead of open-ended planner self-repair.

### `problem-to-plan-trace.json`

Provides bidirectional traceability:

- every workflow stage, skill responsibility, source/representation change,
  external dependency, hook, criterion, test, and TODO maps to a need, problem
  fact, outcome criterion, or necessary risk control;
- every accepted need and outcome criterion maps forward to an implementation
  owner and verification artifact;
- architecture without a need/risk anchor is rejected as speculative scope;
- needs without a planned owner or explicit deferral block acceptance.

## Systematic reasoning sequence

1. Preserve the verbatim request and classify statements as need, observed
   fact, desired outcome, constraint, example, assumption, or solution idea.
2. Build the user-need packet and ask only material outcome-level questions.
3. Frame the implementation-independent problem, retaining rival
   interpretations and marking unsupported causal claims.
4. Freeze the outcome contract and preserved behavior before catalog-driven
   architecture selection.
5. Decide whether existing direct use already satisfies the outcome. If so,
   route directly and avoid change planning.
6. Resolve the relevant existing workflow/run/output when present; otherwise
   identify the workflow family from the required outcome.
7. Search exact workflows, full workflow archetypes, reusable sub-archetypes,
   and composition blueprints in that order; bind the best structural basis and
   record its adaptation delta.
8. Discover and read only the skill bodies needed to validate shortlisted slot
   bindings, fill residual gaps, or assess proposed refinements; then perform semantic reuse,
   sufficiency, source, representation, and external-framework assessments.
9. Generate at least the meaningful alternatives, including a no-change/direct
   route and monotonic extension when applicable. Do not invent alternatives
   solely to satisfy a fixed count.
10. Rank alternatives by outcome coverage, semantic/typed fit, preserved
   behavior, evidence, risk, dependency cost, reversibility, and user
   constraints—not by architectural novelty.
11. Decompose the selected alternative into owned skills/workflow stages and
    bounded integration changes.
12. Generate the problem-to-plan trace, implementation TODO graph, hooks,
    criteria, and tests. Reject orphan architecture and uncovered needs.
13. For a justified skill change, identify the broadest evidence-supported
    reusable boundary, stable contract, variation axes, adapters, consumers,
    exclusions, and transfer fixtures. Then enrich a Codex skill-creator context
    packet; do not turn the problem model into a planner-authored skill.

## Route-specific interpretation

- **Direct use:** the need and outcome contract select and bind an existing
  capability; no implementation architecture is proposed.
- **New workflow:** decomposition begins from the target outcome and stable
  handoffs, not a user-named tool or desired skill list.
- **Extension:** preserve the existing workflow contract and locate the minimum
  addition needed to cover the unmet outcome.
- **Refinement:** begin from observed-versus-expected behavior, reproduce or
  establish it, trace backward, and repair the earliest supported divergence.
- **Report-only change:** permitted only when the desired difference is truly
  presentational and upstream evidence/reasoning is correct.

## Quality and stop rules

The plan is not acceptable when:

- the need is merely a renamed architectural suggestion;
- current and desired behavior cannot be distinguished;
- success cannot be observed or reviewed;
- user facts, planner inferences, and solution hypotheses are conflated;
- one solution is selected before relevant reuse and alternatives are checked;
- TODOs or stages lack a need, outcome, or risk-control anchor;
- an accepted need or preserved behavior has no owner/test/deferral; or
- missing information could materially change scope, authority, causal locus,
  or success.

The planner may return `insufficient_context`, a bounded clarification request,
direct use, a new plan, or a no-change explanation. Producing architecture is
not itself evidence of successful reasoning.
