<!--
SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>

SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
Neuro-symbolic AI Group

SPDX-License-Identifier: Apache-2.0
-->
# Answer trust and generative-masking control

> **Status: implemented; default-off and not yet promoted to enforcement.**
> This model belongs to the planner governance and assessment layer. It does
> not change existing skills, hooks, workflows, Prism files, routing, or
> execution. The completed implementation backlog and receipt are
> [`answer-trust-todos.json`](answer-trust-todos.json).

## Decision

Add two related but deliberately distinct planner artifacts:

1. `answer-control-readiness/v1` is produced after the initial plan is sealed.
   It reports whether the plan contains the controls needed to support a future
   trustworthy answer. It has no answer trust score.
2. `answer-trust-assessment/v1` is calculated only after an exact answer and
   observed execution evidence exist. It scores the grounding and
   hallucination-control posture of that specific answer.

This distinction is non-negotiable. A plan can promise retrieval, provenance,
verification, and review, but promises are not evidence that those operations
occurred. Planned-only input produces `not_calculable`, never a provisional
trust number.

```text
request -> initial plan + digest
        -> existing post-plan evidence verification
        -> answer-control-readiness sidecar
        -> controlled execution and observed receipts
        -> exact answer + component map
        -> answer-trust-assessment sidecar
        -> existing final delivery decision
```

The assessment is planner-level because the planner defines the claim model,
evidence obligations, provenance contracts, scoring policy, invalidation, and
release criteria. It is not a free-form self-rating performed by the model that
generated the answer.

## Meaning and non-meaning of trust

The trust score measures the strength of auditable evidence grounding and
hallucination controls for one exact, versioned answer. It asks whether:

- factual claims use retrieved, observed, or deterministically derived evidence
  rather than model memory or generated text;
- the exact evidence supports the exact predicate and qualifiers;
- evidence can be followed through every transformation into the released
  answer component;
- lossy and generative steps preserve values, units, entities, population,
  specimen, intervention, comparator, outcome, time, uncertainty, conflict,
  and claim ceiling; and
- failures, missing evidence, and contradictions remain visible.

The score is **not**:

- the probability that an answer is true;
- a measure of writing fluency, confidence, citation count, model prestige, or
  source popularity;
- evidence that a planned workflow executed;
- a substitute for clinical, legal, regulatory, or ethical authority;
- permission to average away a fatal provenance or preservation defect; or
- a reason to penalize properly labeled exploration, hypotheses, unknowns,
  user constraints, or prospective methods.

## Threat model: generative masking

Generative masking occurs when generated or semantically transformed material
makes the relationship between an answer and real evidence appear stronger,
cleaner, or more complete than the observed lineage supports.

| Failure mode | Concrete example | Required disposition |
|---|---|---|
| Memory substitution | A model recalls a plausible hazard ratio without retrieving a study or result artifact. | Material factual claim scores `0`. |
| Generated evidence laundering | One model invents a table; another stage consumes it as if it were an observed assay result. | Block affected critical claims; generated ancestors remain generated. |
| Evidence decoration | Real citations are appended after drafting, but no consumed evidence path connects them to the claim. | Claim scores `0`; citation presence gives no credit. |
| Citation or source swap | A source is relevant to the topic but does not contain the asserted predicate, population, or value. | Directness fails; exact-value mismatch may block. |
| Qualifier compression | “Associated in a treated cell line” becomes “causes patient response.” | Preservation fails and the claim-ceiling violation blocks. |
| Missingness masking | Generated prose silently fills an unavailable time point, cohort field, or no-hit source. | Unsupported addition fails; unknown must remain unknown. |
| Aggregation masking | A summary hides sample exclusions, discordant assays, or subgroup direction changes. | Cap until exclusions and conflicts are restored. |
| Synthetic continuity | Imputed or simulated values are presented as measurements. | Block unless clearly typed and used only within their permitted ceiling. |
| Producer self-approval | The same generative invocation creates and solely validates the synthesis. | Generative containment fails; material claim is capped. |
| Retrieval-hint promotion | A search snippet, metadata record, or inaccessible link is presented as full evidence. | Apply its declared access ceiling; no silent promotion. |
| Prompt-injected evidence | Instructions embedded in a paper or retrieved page alter criteria or authority. | Quarantine content; policy and evidence roles remain immutable. |
| Conflict erasure | A synthesis omits material counterevidence found by the workflow. | Conflict control fails; critical claim is capped or blocked. |

Generated text is not intrinsically low trust. A generative step may produce a
high-control synthesis when its evidence envelope is frozen, all factual atoms
are locator-bound, transformations are checked, counterevidence is retained,
and an independent verifier confirms fidelity. Generated material cannot be
its own evidence.

## Required observed inputs

The answer assessment consumes immutable, content-addressed records. It should
reuse the vocabulary and receipts already defined by post-plan evidence
verification and provenance rather than introduce a parallel epistemic model.

- the exact answer digest and addressable output-component map;
- material `ClaimAtom`s plus explicitly exempt non-factual components;
- `EvidenceAtom`s with source identity, authorization, content digest, exact
  locator, access class, directness, applicability, and independence cluster;
- closed `DerivationEdge`s through deterministic, statistical, symbolic,
  generative, and human operations;
- observed `ComputationAtom` or invocation receipts, not planned operations;
- retrospective provenance and planned-versus-observed reconciliation;
- generative envelopes, allowed evidence IDs, prompts/policy digests, output
  schema, abstention behavior, and producer/evaluator identity;
- exact extraction and preservation checks;
- contradictions, negative findings, uncertainty, human reviews, and existing
  quality-gate assessments; and
- the applicable score-policy version and invalidation inputs.

Absent or redacted inputs remain unknown. They never receive assumed credit.
If required observed inputs are missing, the assessment reports an interval or
`not_calculable` rather than manufacturing precision.

## Claim-level model

Each material claim receives six dimensions in `[0, 1]`:

| Dimension | Weight | Observable question |
|---|---:|---|
| `external_grounding` | 0.30 | Is the claim supported by authorized, non-memory evidence with a valid digest and locator that was actually consumed? |
| `lineage_closure` | 0.20 | Is there a complete observed path from evidence through every operation to the exact answer component? |
| `preservation_fidelity` | 0.20 | Did values, units, identities, qualifiers, uncertainty, and claim ceiling survive all transformations? |
| `authority_directness_applicability` | 0.15 | Is the source appropriate for this predicate and applicable to the asserted scope? |
| `generative_containment` | 0.10 | Were generative steps bounded, schema-constrained, abstention-capable, anchor-checked, and independently reviewed? |
| `uncertainty_conflict_control` | 0.05 | Are uncertainty, counterevidence, dependence, missingness, and disagreement represented? |

Use a weighted geometric mean so strength on one dimension cannot compensate
for a zero on another:

```text
raw_claim_score = 100 * exp(sum(weight[d] * ln(max(dimension[d], epsilon))))
claim_score = min(raw_claim_score, applicable_caps)
```

The emitted record retains unrounded values and deterministic calculation
inputs. Only the displayed score is rounded to an integer. Hard gates are
evaluated before score bands.

### Claim classes

- Material factual, computed, causal, and recommendation claims are scored.
- A hypothesis is scored as a *controlled hypothesis*: its label, evidence
  basis, rivals, uncertainty, prohibited promotions, and discriminating test
  matter; lack of confirmatory proof alone is not a defect.
- Explicit unknowns, user preferences, declared constraints, prospective
  actions, and method descriptions are typed and shown as exempt rather than
  falsely treated as unsupported facts.
- Pure deterministic outputs still need input provenance and recomputation, but
  they do not require literature citations merely to describe the transform.

## Gates and caps

Caps are claim-local unless the claim is release-critical or a downstream
claim depends on it. A later fluent synthesis cannot remove an upstream cap.

| Condition | Maximum / consequence |
|---|---|
| Fabricated, unresolvable, unauthorized, or digest-mismatched evidence | `0`; block affected critical claim |
| Material factual claim supported only by model memory, generated text, or a retrieval hint | `0` |
| Citation has no observed `consumed` / `derived_from` path to the claim | `0` |
| Exact value, unit, entity, or direction contradicts the source | `0`; block |
| Causal, clinical, or recommendation posture exceeds its evidence ceiling | `0`; block or demote |
| Planned provenance presented as observed execution | `not_calculable` |
| Generative edge lacks an allowed-evidence envelope or independent fidelity review | cap `25` |
| Exact locator or content digest is absent | cap `40` |
| Material contradiction is unresolved or hidden | cap `50` |
| High-impact human-authority decision lacks named review | cap `60` |
| Critical claim score is below `70` | overall answer cannot enter the high-control band |

Redaction or inaccessible evidence produces a bounded unknown, not a pass.
Duplicate, mirrored, or mutually derivative sources share an independence
cluster and cannot inflate grounding.

## Answer aggregation

First freeze the denominator: all material claims and answer components must be
identified before scoring. Compute:

1. a materiality- and decision-risk-weighted harmonic mean of claim scores;
2. multiply it by material-claim atomization coverage;
3. apply the weakest release-critical claim as an overall ceiling; and
4. apply answer-level hard gates.

The harmonic mean makes weak material claims visible; coverage prevents a
system from scoring only the easiest sentences. The result includes both the
overall score and the complete claim ledger.

Unassessed dimensions are evaluated twice, as `0` and `1`, to emit a lower and
upper bound. An interval wider than 20 points or incomplete material-claim
coverage produces `insufficient_evidence`, not a crisp classification.

### Display bands

| Score | Label | Meaning |
|---:|---|---|
| 85–100 | `high_control` | Strong observed grounding and preservation; all critical gates pass. |
| 70–84 | `substantiated` | Auditable evidence supports the answer with bounded caveats. |
| 50–69 | `guarded` | Useful only with visible limitations or unresolved controls. |
| 25–49 | `low` | Material grounding or preservation is weak. |
| 0–24 | `blocked_untrusted` | Unsupported or fatally masked material claims. |

The label describes control posture, not truth probability.

## Anti-masking diagnostics

Every assessment emits at least:

- `grounded_material_claim_coverage`;
- `memory_only_claim_rate`;
- `unsupported_generative_addition_rate`;
- `citation_lineage_mismatch_rate`;
- `preservation_failure_rate`;
- `observed_vs_planned_lineage_coverage`;
- fraction of answer content that is evidence-backed, deterministic,
  generative-but-verified, hypothesis, unknown, or exempt;
- weakest material and release-critical claims;
- applied gates and caps with exact evidence anchors; and
- bounded remediation actions that would change the assessment.

Adding citations, sources, verbosity, or evaluator confidence without improving
the exact claim lineage must not improve the score.

## Planner integration

### Planning-time readiness

Extend the existing digest-bound post-plan verification concept with a pure
readiness sidecar. It should identify:

- planned material claim classes and release-critical claims;
- real-evidence acquisition and exact-locator obligations;
- steps where model memory or generated intermediates could become implicit
  evidence;
- every lossy or generative edge and its preservation contract;
- deterministic replacements for exactly checkable operations;
- counterevidence, independence, uncertainty, and review obligations;
- expected receipts required to make the final score calculable; and
- the maximum attainable band if the current plan executes exactly as written.

The last item is a named `attainable_control_band`, not a numeric answer trust
score. Readiness findings remain proposals through the existing refinement
cycle and cannot mutate the sealed initial plan.

### Post-execution assessment

Add a pure answer assessment after component provenance reconciliation and
artifact quality assessment, but before final delivery authorization. The
assessment can narrow or block delivery; it cannot override an existing
must-pass failure or broaden authority.

Candidate future surfaces are:

- `app/backend/lunar_planner/answer_trust.py` for deterministic
  assessment mechanics;
- packaged schemas for readiness and answer assessment;
- the planner manifest and contracts registry;
- provenance/component reconciliation as observed-input adapters;
- a profile stage between observed artifact assessment and final delivery;
- user-facing reasoning events and delivery trust cards; and
- a dedicated adversarial benchmark under `benchmarks/planner/`.

Do not overload the existing `TrustPolicy` port: it governs operation
authorization, not epistemic trust in an answer. Do not attach a realized
answer score to the route-only `run_planner_request()` path.

## User-facing trust card

Before execution, communicate the readiness posture: evidence routes, planned
preservation checks, generative boundaries, critical claims, known gaps, and
which receipts will be required.

After execution, show:

- status, score interval, display band, and policy version;
- material-claim coverage and generated-versus-grounded composition;
- the weakest critical claims and why they are weak;
- hard gates/caps and unresolved contradictions;
- representative evidence anchors and provenance coverage;
- what is a fact, derivation, hypothesis, unknown, or recommendation; and
- concrete remediation, without exposing hidden chain-of-thought.

The concise card links to the full machine-readable claim ledger.

## Calibration and anti-gaming

- Scoring is deterministic from sealed records; a model may extract candidate
  claims or flag risks but may not assign itself evidence credit.
- Freeze claims and denominator before scoring.
- Deduplicate source independence clusters and test citation swaps.
- Require predicate support, not topical relevance.
- Preserve no-hit sources, exclusions, negative results, and contradictions.
- Adding irrelevant or duplicate evidence is score-invariant.
- Removing a valid critical provenance edge cannot increase trust.
- Adding valid independent evidence cannot reduce trust unless it introduces a
  real contradiction, which must remain visible.
- Weights, thresholds, and mappings are versioned and calibrated on a sealed,
  human-reviewed corpus, never tuned on release candidates.
- Report false-block rates separately for exploration, deterministic outputs,
  unknowns, and user constraints so safety does not become indiscriminate
  skepticism.

## Biomedical examples

### High-control evidence synthesis

A report claim links to a primary study paragraph and table cell, preserves the
cohort, intervention, endpoint, value, unit, and date, records an observed
retrieval digest, and passes independent generative fidelity review. A
contradictory study is retained and narrows the claim. The answer may reach
`high_control` if all other critical claims also pass.

### Real citation, masked claim

The answer says a treatment improves overall survival and cites a real trial,
but the cited locator reports progression-free survival in a subgroup. The
source is real but the predicate and endpoint do not match. Directness and
preservation fail; the critical claim is blocked.

### Plasma multiomics missingness

A generative stage receives sparse assay summaries and fills an absent time
point to create a smooth trajectory. Even if biologically plausible, the value
is synthetic. If later prose presents it as measured plasma evidence, the
claim scores `0`. If it is explicitly typed as imputation, retains observed
versus imputed masks, and is used only for a bounded sensitivity analysis, it
can support a controlled model-based statement.

### Controlled exploratory hypothesis

A workflow proposes that discordant proteomic and metabolomic trajectories may
reflect treatment timing. It links the observed discordance, labels the idea as
a hypothesis, gives rival explanations, exposes missing collection metadata,
and specifies a discriminating test. The hypothesis can score highly as a
well-controlled hypothesis without being promoted to an established mechanism.

### Planned-only workflow

A plan promises database retrieval, exact extraction, provenance, and review,
but no run exists. Readiness may be strong. Answer trust remains
`not_calculable` because no answer or observed evidence path exists.

## Rollout

1. Specify semantics, schemas, threat fixtures, and golden non-interference
   baselines.
2. Add planning-time readiness in report-only shadow mode.
3. Build observed-input adapters and an offline deterministic scorer.
4. Run adversarial and anti-paranoia benchmarks without affecting delivery.
5. Calibrate bands against sealed human review and publish disagreements.
6. Add user-facing trust cards in shadow mode.
7. Authorize delivery blocking only after escape-rate, false-block,
   reproducibility, and compatibility gates pass.

Rollback disables the additive assessment stage and leaves existing planner,
quality, provenance, skill, hook, workflow, and Prism behavior unchanged.

## Success criteria

- Planned-only material never receives an answer trust score.
- Every displayed score is exactly reproducible from emitted claim records and
  a versioned policy.
- Fabricated exact values, unsupported generative additions, and citation-lineage
  mismatches are detected in all disclosed fixtures.
- Duplicate or irrelevant evidence cannot improve the score.
- A missing critical provenance edge cannot increase the score.
- Critical gates cannot be hidden by a high aggregate.
- Explicit unknowns and properly bounded hypotheses are not falsely blocked.
- Existing planner behavior is byte-equivalent when the feature is disabled.
- Existing skills, hooks, workflows, and Prism files are untouched by the
  planning and shadow-mode increments.
