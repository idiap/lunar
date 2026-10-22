<!--
SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>

SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
Neuro-symbolic AI Group

SPDX-License-Identifier: Apache-2.0
-->
# Exploratory discovery planning contract

## Research stance

The planner supports exploratory research. Its goal is to create workflows that
produce useful, discriminating learning and defensible next hypotheses—not to
demand proof-level certainty before any discovery claim can be made.

Uncertainty is something to characterize, exploit, and reduce selectively. It
is not an automatic blocker. The planner proceeds with explicit assumptions and
calibrated exploratory claims whenever inputs, authority, and analysis validity
are sufficient. It blocks only when an unresolved issue would make the question
meaningless, the computation invalid, the scope unauthorized, or the output
materially misleading.

Claim calibration remains mandatory. Exploratory freedom does not authorize
causal, predictive, clinical, or generalizable claims beyond the evidence. The
planner should help users make the strongest supportable provisional claim,
state what would change it, and identify the next high-value test.

## Assumption elicitation

Before architecture selection, the planner creates
`discovery-assumption-register.json`. It critically surfaces assumptions about:

- scientific scope, population, context, comparator, and intended use;
- biological mechanism, causal direction, and alternative explanations;
- data availability, representativeness, missingness, labels, and selection;
- measurement validity, preprocessing, identifiers, and representations;
- statistical/model behavior, thresholds, confounding, leakage, and stability;
- evidence sources, freshness, transportability, and claim boundaries; and
- operational feasibility, tools, dependencies, authority, budget, and time.

Each assumption records whether it came from the user, evidence, an existing
workflow, or planner inference; its current support, uncertainty, consequence
if false, sensitivity, testability, disconfirming observation, and disposition:
`accept_provisionally`, `test_now`, `test_later`, `bound_output`, `ask_user`, or
`block`. The planner prioritizes assumptions whose failure would most alter the
question, workflow, ranking, or interpretation. It does not create an exhaustive
inventory of harmless background beliefs.

Questions to the user are limited to facts or preferences only the user can
resolve and whose answer materially changes scope, meaning, authority, or
success. Testable scientific uncertainty becomes a workflow question or TODO,
not an interrogation that prevents planning.

## Critical discovery questions

`critical-discovery-questions.json` contains a small ranked set of questions
that change the discovery landscape. Candidate questions are ranked by:

- information gain and ability to distinguish competing hypotheses;
- effect on candidate ranking, workflow route, or follow-up decisions;
- falsifiability and a clear answer shape;
- novelty leverage without novelty-for-its-own-sake;
- feasibility, cost, source availability, and time;
- orthogonality to evidence already collected; and
- ability to reveal a dead end, transportability limit, or justified pivot.

Each question records why it matters, linked assumptions/hypotheses, required
evidence, expected answer shapes, what observations would change the plan, the
responsible workflow stage, and the cost of leaving it unanswered. Low-value
questions that merely request more evidence without changing a decision are
deferred. A default shortlist may contain roughly three to six questions, but
the information structure—not a fixed count—determines the final set.

## Discovery success contract

`discovery-success-contract.json` defines success in user-facing terms before
the workflow is designed. It separates four increasing levels:

1. `learning_advance` — an important assumption or hypothesis is supported,
   weakened, refuted, bounded, or made testable; a well-designed null result or
   dead-end map can satisfy this level.
2. `discovery_lead` — a reproducible pattern, candidate, contrast, or mechanism-
   consistent hypothesis is prioritized over explicit alternatives with
   traceable evidence and limitations.
3. `follow_up_ready` — the result identifies a feasible discriminating next
   experiment, cohort analysis, source acquisition, or validation route.
4. `validation_ready` — prespecified robustness, transport, or independent
   validation evidence supports promotion beyond an exploratory claim.

An exploratory workflow normally targets one of the first three levels.
`validation_ready` is not silently imposed as the definition of discovery.
Every contract states the target level, observable indicators, minimum evidence,
negative/null-result value, acceptable uncertainty, disqualifying artifacts,
claim language, stop/pivot conditions, resource budget, and the end-user
decision enabled.

## Claim and action policy

Permitted exploratory outputs include observations, exploratory associations,
ranked candidates, abductive hypotheses, mechanism-consistent interpretations,
contrasts, anomalies, and validation candidates. Language identifies them as
provisional and records alternative explanations.

The planner does not require all assumptions to be resolved or every result to
be independently validated before returning a discovery lead. Conversely, it
does not turn novelty, model confidence, or repeated internal consistency into
causal or clinical proof. The claim level and the success level are related but
separate: a workflow can achieve substantial learning while correctly retaining
a modest claim ceiling.

## Stop, continue, and pivot

Continue when a bounded next step has material expected information gain and is
within authority and budget. Pivot when current hypotheses repeatedly stall,
contradictions suggest a different framing, or a new evidence axis is more
discriminating. Stop successfully when the target discovery-success level is
met, when a meaningful hypothesis has been refuted or bounded, or when a clear
next action is enabled. Stop as a documented dead end when expected information
gain is too low relative to cost.

The planner must not continue indefinitely in pursuit of certainty. It records
residual uncertainty and the evidence needed for any later claim promotion.

## User-facing reasoning log

The reasoning log shows the prioritized assumptions, critical questions,
target discovery-success level, current learning, claim ceiling, and stop/
continue/pivot rationale. It explains uncertainty without making the workflow
sound defective merely because it remains exploratory.
