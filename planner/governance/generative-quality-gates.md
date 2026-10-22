<!--
SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>

SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
Neuro-symbolic AI Group

SPDX-License-Identifier: Apache-2.0
-->
# Elicited generative quality gates

## Principle

Quality criteria are an essential planning artifact, not a final checklist added
after implementation. Before every critical decision or handoff, the responsible
criteria owner elicits what good performance means for that context, how it will
be observed, and what happens when the result is weak, mixed, or surprising.

Most scientific and planning quality is semantic: relevance, coherence,
discriminating power, explanatory value, calibrated uncertainty, usefulness,
and fit to the user's discovery need. These criteria are generative by default.
Deterministic checks remain authoritative for schemas, identities, provenance,
permissions, dependency pins, exact invariants, and reproducible calculations.
Human review is used for value-laden or preference-sensitive judgments that
cannot be delegated safely.

Generative assessment is evidence about quality, not deterministic proof. It
must not be used to override failed safety, authority, provenance, or contract
checks.

## Resumable two-freeze routing

Consequential closure—an explicit multi-stage/composition consequence profile,
an explicit human-authority decision, or the final route-lock/candidate-
production turn of a reusable workflow—advances through three sealed planner
calls. Exploratory workflow drafting remains revisable until that closure:

1. Frame and decompose the request, emit a provisional outcome-quality
   contract, and stop with `quality_planning_required`. Candidate retrieval and
   semantic route selection have not started.
2. Resume with `frozen_outcome_quality_contract` and its independently passing
   `outcome_quality_review`. The planner validates the exact frame,
   requirements, principal, catalog snapshot, provisional-review digest, and
   freeze lineage before selecting a route. It then emits a provisional
   route-delivery plan and stops with `delivery_quality_planning_required`.
3. Resume with `frozen_delivery_quality_plan` and its independently passing
   `delivery_quality_review`. Only an exact outcome/route-bound freeze can
   produce the route-locked candidate-delivery handoff. Artifact assessment and
   final release authorization remain separate downstream gates.

The continuation envelope is content-addressed. A changed catalog snapshot,
request frame, requirement ledger, principal, reviewed byte, outcome parent, or
selected target fails closed rather than silently restarting or weakening the
quality bar.

Ordinary one-step direct requests currently retain the original compatibility
path: they route while emitting provisional, catalog-invariant outcome and
delivery criteria, but cannot authorize candidate production or final release.
This is an explicit migration exception, not evidence that the universal
pre-route-freeze acceptance condition is complete.

## Critical points

A point requires an explicit quality gate when its output materially determines:

- interpretation of the user's need, problem, assumptions, or intended outcome;
- discovery questions, success level, evidence boundary, or claim language;
- direct reuse versus extension/new-workflow architecture;
- source, representation, external framework, dependency, or handoff semantics;
- workflow decomposition, stage ownership, or terminal artifact;
- TODO scope, success criteria, test strategy, or plan acceptance;
- a created/updated skill, candidate workflow run, or user-facing report; or
- refinement, pivot, promotion, or closure.

Routine deterministic transitions do not need invented semantic rubrics. The
quality-gate plan records why each point is critical and why any apparent
critical point is safely excluded.

## Artifacts

`quality-gate-plan.json` is created after the discovery-success contract and
before catalog-driven architecture. For each gate it records:

- gate ID, critical point, owner, evaluated artifact, downstream decision, and
  failure consequence;
- criterion source: user need, discovery-success contract, domain standard,
  accepted workflow contract, consumer contract, or explicit planner inference;
- deterministic, generative, and human-review criteria with precedence;
- generative rubric dimensions, positive/negative/edge exemplars, acceptable
  variation, disqualifiers, and evidence required;
- evaluator identity and separation from the producer, context allowed,
  withheld labels/answer keys, model/configuration, trials justified by risk,
  and cost/timeout;
- outcomes: `pass`, `revise`, `pivot`, `defer`, `block`, or `inconclusive`, with
  bounded re-entry and stop rules; and
- invalidation inputs and the plan version that froze the criteria.

Each gate produces an immutable `quality-gate-assessment.json`. Criteria and
assessment digests are linked to the stage artifact, reasoning-log event, TODOs,
and validation evidence. Criteria are frozen before the evaluated artifact is
generated or selected. New evidence may justify a versioned revision, never a
silent post-hoc rewrite that converts failure into success.

## Generative rubric design

Generative criteria should be discriminating and observable. Depending on the
gate they evaluate whether the result:

- answers the actual user/discovery question rather than a convenient proxy;
- distinguishes meaningful alternatives and explains why-not decisions;
- uses evidence at the right directness and preserves source boundaries;
- exposes consequential assumptions and uncertainty without paralysis;
- provides a coherent, typed, reusable handoff to its consumer;
- advances the declared discovery-success level, including through informative
  negative or refutational learning;
- supports the strongest calibrated exploratory claim without overpromotion;
- enables a clear next action, stop, or pivot; and
- avoids generic prose, unsupported completeness, and apparent precision.

Rubrics use concise anchored levels rather than one vague score. Thresholds may
combine must-pass dimensions with an aggregate judgment. A high average cannot
cancel a fatal provenance, authority, claim-boundary, or contract defect.

## Evaluation independence and leakage control

Where feasible, the producer and evaluator are separate invocations. The
evaluator receives the frozen rubric, user need, allowed evidence, and candidate
artifact, but not hidden answer keys, intended wording, producer scratch work,
or withheld validation data. The evaluator reports criterion-level findings and
evidence anchors rather than uninspectable preference.

Self-assessment may nominate concerns but cannot be the sole release evidence at
a material critical point. Ambiguous or high-impact gates use risk-proportional
replication or human adjudication. Disagreement is retained as uncertainty; it
is not averaged away silently.

## User-facing behavior

The reasoning log shows the current critical point, elicited quality bar, why it
matters, assessment outcome, evidence, and resulting pass/revise/pivot/defer/
block decision. It presents criteria in end-user language and links detailed
rubrics on demand.

The framework does not gate every exploratory idea into immobility. Criteria
must match the declared discovery-success level: exploratory leads are judged
for learning value, discrimination, traceability, and calibrated claims—not for
validation-level certainty unless that is the accepted target.
