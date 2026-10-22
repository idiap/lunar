<!--
SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>

SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
Neuro-symbolic AI Group

SPDX-License-Identifier: Apache-2.0
-->
# Workflow effort, time-savings, token, and cost estimation

> **Status: planned; implementation is not authorized by this document.**
> This is an optional planner-level assessment. It is disabled by default and
> must not change scientific routing, workflow structure, evidence controls,
> answer-trust decisions, execution authority, or release decisions.

The machine-readable implementation backlog is
[`workflow-effort-and-cost-estimation-todos.json`](workflow-effort-and-cost-estimation-todos.json).

## Decision

Add a default-off planner overlay named `workflow_economics`. It prepares an
auditable comparison between a scientific workflow and an output-equivalent
traditional, non-agentic process. It also estimates prospective resource use
and reconciles observed token and direct execution costs when authoritative
runtime receipts are available.

The planner owns the comparison contract, workload decomposition, uncertainty
policy, aggregation, and presentation. The host runtime owns telemetry
collection. Providers remain authoritative for reported token usage and
billing exports. The planner must not infer observed execution from a plan.

The overlay produces separate artifacts rather than one opaque efficiency
score:

1. `workflow-effort-estimate/v1` — prospective manual-equivalent and assisted
   human effort with uncertainty.
2. `workflow-effort-assessment/v1` — retrospective effort assessment using
   observed workflow and human-review receipts.
3. `workflow-resource-estimate/v1` — prospective token, API, compute, storage,
   and direct-cost envelope.
4. `workflow-resource-usage/v1` — observed usage normalized from runtime and
   provider receipts.
5. `workflow-cost-reconciliation/v1` — estimate, reservation, observed spend,
   and invoice-reconciled spend without changing their evidence states.
6. `workflow-economics-report/v1` — a user-facing bundle with component
   breakdowns, ranges, coverage, assumptions, and sensitivity drivers.

No artifact may collapse human effort, calendar time, tokens, direct machine
cost, and optional labor valuation into a single number.

```text
explicit request or opt-in flag
  -> sealed workflow plan and scientific acceptance contract
  -> frozen output-equivalent traditional comparator
  -> atomic workload inventory
  -> prospective effort and resource estimates
  -> optional separately authorized budget reservation
  -> controlled execution with usage and review receipts
  -> retrospective effort and usage assessment
  -> optional invoice reconciliation
  -> workflow economics report
```

## Invocation and authority

The overlay is not automatically attached to normal planning. Invocation
requires one of:

- an explicit user request for effort, time-savings, token, or cost estimates;
- a dedicated planner API flag or economics profile; or
- a post-run request against an already sealed workflow/run.

Suggested modes are `off`, `estimate`, `observe`, and `budget`:

| Mode | Meaning | Authority |
|---|---|---|
| `off` | No economics sidecar or artifact. | Existing planner behavior remains identical. |
| `estimate` | Prospective effort and resource ranges only. | Advisory and non-executing. |
| `observe` | Prospective estimates plus authorized retrospective reconciliation. | Reads supplied receipts; cannot authorize execution. |
| `budget` | Adds an explicitly authorized reservation or stop policy. | Budget policy may constrain spend but cannot change scientific validity. |

Economics may help a human choose among already scientifically acceptable
options. It must never make an invalid workflow acceptable, lower evidence or
review requirements, silently select a cheaper provider, or block scientific
release merely because a workflow is expensive. Budget enforcement, when
explicitly enabled, is a resource authority decision and remains separate from
scientific quality and release authority.

## The comparison contract

Time savings are meaningful only when the comparator delivers the same thing.
Every estimate therefore freezes a `ComparatorContract` before calculating a
headline number.

The contract records:

- the exact workflow/plan digest and workload-manifest digest;
- deliverable type, scope, source cutoff, and intended consumer;
- evidence coverage, provenance, reproducibility, and acceptance tests;
- required review, approval, risk, and authority boundaries;
- experienced practitioner or declared team-role mix;
- ordinary non-agentic tools available to the comparator, such as search
  portals, reference managers, spreadsheets, scripts, and statistical tools;
- reusable assets available to both scenarios;
- one-time setup, learning, procurement, wet-lab, and other exclusions; and
- comparator-policy and calibration-profile digests.

The comparator is an experienced practitioner completing the same controlled
deliverable, not a novice learning the domain from scratch. An audited agentic
report cannot be compared with an informal manual answer. If the acceptance
criteria are absent, the deliverables differ materially, or equivalent quality
cannot be defended, the result is `not_estimable`.

## Four clocks that must remain distinct

1. **Human active effort** is additive person-time spent doing or reviewing
   work. This is the primary time-savings measure.
2. **Human waiting time** is elapsed time during which a person is blocked but
   not actively working.
3. **Machine/agent runtime** is compute elapsed time. It is neither human labor
   nor proof of avoided labor.
4. **End-to-end calendar duration** follows the dependency graph and critical
   path. Parallel work may reduce duration without reducing person-hours.

For example, two researchers working two hours in parallel represent four
person-hours and a two-hour critical path. A valid report must not call the
manual baseline two person-hours.

## Atomic workload inventory

The estimator compiles the sealed stage DAG into non-overlapping `WorkUnit`s.
Each unit has a stable ID; parent stage and input/output artifact IDs; activity
class; role; quantity and unit; dependencies; multiplicity; rigor/risk tier;
setup, review, and rework drivers; and prospective or observed receipt links.

Recommended activity classes are:

| Activity | Example measurable drivers |
|---|---|
| Framing and protocol | questions, criteria, outcomes, protocol revisions |
| Discovery and access | queries, databases, candidate records, files opened, access failures |
| Screening and evidence selection | titles/abstracts screened, full texts adjudicated, reviewers, disagreements |
| Reading and interpretation | relevant pages, tables, figures, supplements, documentation depth |
| Extraction | claims, fields, estimates, study-design elements, locators, double-extraction requirement |
| Normalization and linkage | identifiers, units, schemas, populations, endpoints, unresolved mappings |
| Data staging | files, tables, samples, modalities, cleanup and inclusion decisions |
| Computation and analysis | methods, models, contrasts, plots, diagnostic runs, debugging cycles |
| Consolidation and synthesis | claim-evidence rows, sources compared, contradictions, uncertainty statements |
| Verification and critique | arithmetic/schema checks, citation entailment, source replay, adversarial review |
| Revision and remediation | failed checks, corrections, reruns, escalations, exception handling |
| Coordination and governance | handoffs, approvals, reviewer reconciliation, access/consent decisions |
| Packaging and communication | tables, figures, report sections, references, exports, final inspection |
| Cross-stage integration | pipeline glue, provenance wiring, reproducibility hardening, global review |

A stage combining search, reading, extraction, and synthesis becomes multiple
child units. Units are deduplicated by operation and output-artifact identity.
One source opened once cannot earn savings credit in several stages unless
distinct work on it is explicitly represented.

## Human-effort model

Each work unit uses distributions or bounded scenarios rather than an
unqualified constant. A conceptual manual baseline is:

```text
manual_i = setup_i
         + quantity_i * manual_rate_i * complexity_i * friction_i * rigor_i
         + coordination_i
         + expected_manual_rework_i
```

The assisted residual is constructed independently:

```text
assisted_i = human_setup_i
           + work_not_automated_i
           + mandatory_review_i
           + approval_i
           + expected_correction_i
           + escalation_i
           + assisted_coordination_i

expected_correction_i = P(defect_or_escalation_i) * correction_effort_i
```

Workflow totals are:

```text
manual_person_hours   = sum(manual_i)
assisted_person_hours = sum(assisted_i)
net_saved_hours       = manual_person_hours - assisted_person_hours
saving_fraction       = net_saved_hours / manual_person_hours
```

Negative savings remain negative. They are useful evidence that setup,
review, or remediation costs exceed displaced work. The implementation must
not clamp an unfavorable result to zero.

Reports also distinguish:

- gross work displaced by automation;
- work that remains manual;
- new assurance/review work introduced by the agentic process;
- net person-hours saved;
- manual and assisted critical-path duration;
- one-time setup versus marginal per-run effort; and
- the declared repetition/amortization horizon.

## Detailed activity heuristics

### Reading

Reading is modeled by evidence type and depth, not just document count. Inputs
may include pages or words, tables/figures/supplements, methodological
complexity, relevance density, note-taking/extraction requirements, and
critical-reading tier. Metadata inspection, abstract triage, targeted table
lookup, and full-text critical reading are different units. A citation list is
not evidence that the workflow read the sources.

### Evidence selection

Selection separates query design, deduplication, title/abstract screening,
full-text eligibility, authority/applicability review, and disagreement
resolution. The denominator is the complete candidate population observed at
the frozen cutoff. The estimator cannot count only included evidence while
omitting screening effort.

### Extraction and normalization

Drivers include claims or fields extracted, source layout, schema stability,
locator requirements, units and identifiers normalized, crosswalk ambiguity,
and independent double extraction for high-risk facts. Missing values and
unresolved mappings create explicit exception work; they are not assumed free.

### Consolidation and synthesis

Drivers include claim-evidence rows, source heterogeneity, comparison groups,
contradictions, uncertainty, provenance joins, and narrative/report sections.
Fluent text length is not a substitute for the number of evidence relationships
that had to be reconciled.

### Verification, revision, and governance

Mandatory review floors follow risk and publication/clinical/regulatory impact.
The model includes source replay, arithmetic/schema checks, citation
entailment, contradiction review, reviewer reconciliation, approvals, failed
runs, correction, and reruns. Removing review to improve a savings estimate is
prohibited.

## Grounding and uncertainty

Every quantity, rate, multiplier, and review floor carries a source class,
reference, timestamp, applicability statement, and confidence reason.
Precedence is:

1. observations from the exact workflow and matched manual comparator;
2. frozen blinded benchmark measurements;
3. organization-approved matched component/domain profiles;
4. calibrated analogous profiles;
5. structured expert elicitation; and
6. conservative generic priors.

Generic priors are planning assumptions, not measurements. Missing telemetry
widens uncertainty or yields `not_estimable`; it never means zero effort.

Use bounded triangular, lognormal, or empirical distributions as appropriate
for nonnegative effort and preserve important correlations, such as candidate
count driving both screening and reading. Seeded Monte Carlo or deterministic
scenario propagation emits at least P10/P50/P90. Confidence/evidence grade is
reported separately from interval width. The output names the largest
sensitivity drivers and which missing observation would most reduce
uncertainty.

## Token and direct-resource model

Prospective resource estimates are derived per component and attempt from:

- invocation and retry distributions;
- uncached input tokens;
- cached-input reads and cache writes where separately billed;
- output tokens;
- provider-specific reasoning or other token classes only where meaningful;
- embeddings and vector operations;
- paid search, literature, database, OCR, or other API operations;
- CPU/GPU time, memory, storage, and data transfer;
- fixed request, per-run, service, or explicitly supplied license charges; and
- expected failed or cancelled billable attempts.

Observed token usage follows the existing runtime-event rule: use
provider-reported SDK usage only. Locally tokenized counts may be labeled
`tokenizer_derived`, never `provider_observed`. A configured context or token
budget is not consumption.

Every resource line has one evidence state:

| State | Meaning |
|---|---|
| `invoice_reconciled` | Matched to an authoritative billing export or invoice. |
| `provider_observed` | Returned by the provider/runtime usage receipt. |
| `meter_observed` | Locally measured compute, storage, network, or execution quantity. |
| `tokenizer_derived` | Calculated with a pinned provider-compatible tokenizer. |
| `profile_estimated` | Predicted from a sufficiently sampled, current calibration profile. |
| `heuristic_estimated` | Cold-start bounded assumption. |
| `not_calculable` | Quantity, accounting semantics, or price is unavailable. |

Mixed reports expose coverage by evidence state. They do not promote the whole
report to “observed” because one line has a receipt.

## Provider accounting semantics

Provider adapters preserve the raw usage object and emit normalized,
non-overlapping billing quantities. Each adapter version declares:

- whether cached input is included in or excluded from total input;
- whether reasoning tokens are included in output tokens;
- whether tool arguments/results are already represented in token totals;
- how batch, service-tier, region, and priority multipliers apply;
- whether failed and cancelled requests are billable; and
- whether rounding occurs per request, line item, or invoice.

Retries and failed billable attempts remain actual usage. External tool/API
fees are separate cost lines even when tool results also entered model context.
Shared orchestration cost uses a declared allocation policy (`direct`, `equal`,
`proportional_to_tokens`, `proportional_to_runtime`, `causal_owner`, or
`unallocated`). An honest `unallocated` bucket is preferable to invented
precision.

## Pricing snapshots and arithmetic

Mutable commercial prices are not hardcoded in estimator logic. A content-
addressed price book records provider, model/service, region, tier, effective
interval, currency, unit dimensions, cache/batch semantics, rounding, source
locator, retrieval timestamp, authority status, and digest. Usage is priced
against the snapshot effective at the event timestamp, preserving historical
replay after prices change.

For attempt `a` of component `c`:

```text
cost(c,a) = sum_k(quantity(c,a,k) * rate(k) / rate_unit(k))
          + fixed_request_cost
          + external_tool_cost
          + compute_cost
          + storage_cost
          + network_cost
```

Use integer nano-currency units or fixed-decimal arithmetic. Unsupported token
classes, models, currencies, contractual rates, or regions remain unpriced and
reduce cost coverage. Missing price never becomes zero. Currency conversion is
optional and requires a separately pinned FX snapshot.

## Budget reservation and reconciliation

Budget mode is a separately authorized extension of estimation. A prospective
reservation may use P90 direct spend plus a declared safety margin and known
fixed charges. Counters distinguish actual reconciled, observed-not-invoiced,
and reserved spend. Applicable run, workflow, principal, tenant, provider, and
time-window locks are acquired in deterministic order.

Reconciliation verifies identities, releases the reservation, adds observed or
invoice spend, retains variance, handles partial/late/cancelled receipts, and
is idempotent. Persistence should follow CostGuard conventions: confined
relative paths, atomic JSON replacement, append-only locked JSONL ledgers,
canonical digests, privacy-scope separation, and concurrency tests.

## Privacy and non-surveillance boundary

The model estimates a task process, not an individual employee. It must not
infer personal productivity, salary, performance, or historical work habits.
Optional observation captures aggregate task-level quantities and active/review
time only with authorization.

Usage artifacts may contain opaque IDs, counts, timestamps, component labels,
provider/model identifiers, and aggregate cost lines. They must exclude prompts,
response bodies, hidden reasoning, source content, credentials, headers,
patient-level rows, and sensitive low-entropy values disguised as hashes.
Tenant, principal, and privacy scope remain part of every join and retention
decision.

Human labor valuation is optional and requires explicit role rates, currency,
scope, and source. It remains a separate scenario from direct execution cost.
The planner must not infer financial ROI by silently assigning salaries.

## Invalidation and replay

- A workflow, acceptance-contract, workload, or baseline-policy change
  invalidates effort estimates.
- A run or human-review receipt change invalidates retrospective effort.
- A usage-receipt or provider accounting-semantics change invalidates usage and
  cost reconciliation.
- A price-book change invalidates cost only; it does not change observed token
  counts or human effort.
- A currency/FX change invalidates converted presentation only.

All calculations retain exact inputs, policy and calibration digests, seed,
unrounded values, and deterministic replay receipts.

## Calibration and promotion

Effort calibration uses matched tasks whose manual and assisted outputs both
pass the same scientific acceptance tests. Independent experienced reviewers
estimate or perform work blind to the system estimate. Metrics include signed
bias, absolute error, interval coverage, residual-effort underestimation,
false-positive “time saved” rate, inter-reviewer disagreement, and quality
parity.

Resource calibration groups privacy-filtered telemetry by component family,
provider/model/tier, input-size band, evidence volume, artifact type, critique
depth, tool count, and cache posture. Metrics include quantile loss, P50 error,
P90 coverage, budget-overrun rate, retry calibration, unpriced coverage, drift,
and invoice discrepancy.

Profiles require minimum sample size, recency, domain/risk coverage, and frozen
held-out evaluation. Synthetic fixtures prove mechanics, not real-world
calibration. Rollout advances through `off`, `fixture`, `shadow`, `audit`, and
`advisory`. There is no scientific enforcement state. A separately authorized
budget state may enforce only resource limits.

## User-facing report

The primary report should lead with a range and evidence status, for example:

> For the frozen report workflow, the output-equivalent traditional process is
> estimated at 72–118 experienced-person hours (median 91). Assisted human
> setup, review, correction, and approval are estimated at 18–31 hours (median
> 23), yielding a net saving of 49–91 hours (median 68; 75%). The largest
> uncertainty is full-text screening depth. This is a calibrated analogue, not
> observed employee productivity.
>
> Prospective model usage is 1.2–2.0 million input-equivalent tokens and
> 90–160 thousand output tokens. Estimated direct cost is USD 18–34 against
> price-book digest `sha256:…`; 82% is priced and the remaining API category is
> unknown. No execution or spend is implied by this estimate.

The card then shows component effort, residual human review, token classes,
direct cost subtotals, unallocated/shared overhead, evidence grades,
assumptions/exclusions, sensitivity drivers, and prospective-versus-observed
labels.

## Concrete examples and required dispositions

| Case | Required result |
|---|---|
| Evidence synthesis with 400 hits, 60 abstracts, 12 full texts, and 40 extracted claims | Separate search, screening, reading, extraction, consolidation, verification, and reporting. Without receipts, realized reading/screening remains unknown. |
| Manual process 90 minutes; assisted setup/review/correction 105 minutes | Report `-15` minutes net saving, not zero or a positive claim. |
| Two researchers work two hours in parallel | Report four person-hours and a two-hour critical path. |
| Agent creates a short summary while comparator requires claim locators and contradiction checks | `not_equivalent` and `not_estimable`. |
| Plan budgets 200,000 tokens but runtime reports no usage | Prospective budget only; observed usage is `not_reported`. |
| Provider reports input total including cached tokens | Normalize once according to the pinned accounting adapter; do not add cached tokens again. |
| One failed and one successful billable attempt | Both attempts count in observed usage and cost. |
| Tokens reported but model price absent | Report tokens as observed and monetary cost as partially or wholly `not_calculable`. |
| Current price differs from the execution-date price | Reconcile with the effective historical snapshot; current price may appear only in a labeled scenario. |
| A shared orchestration call serves three branches | Apply the declared allocation policy or leave it `unallocated`; do not charge it three times. |
| Cached evidence is reused on ten runs | Amortize setup once under the declared horizon; do not claim its creation as newly saved ten times. |
| Prospective residual review was 3–5 hours but observed review was 7 | Preserve the overrun, update calibration diagnostics, and do not rewrite the original estimate. |

## Implemented completion boundary

The implementation receipt records completion only when every headline value decomposes to typed work
or resource lines with provenance; all estimates and observations retain their
polarity; negative and not-estimable cases work; missing usage/price never
becomes zero; disabled planner outputs and digests remain unchanged; no
scientific route or release decision is affected; strict schemas, deterministic
replay, adversarial benchmarks, standalone distribution, and full planner tests
pass; and advisory promotion remains off until real held-out calibration meets
declared thresholds.
