<!--
SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>

SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
Neuro-symbolic AI Group

SPDX-License-Identifier: Apache-2.0
-->
# Post-plan evidence and determinism verification

## Decision

Add a planning-only `epistemic-verification-overlay/v1` after the initial
workflow instantiation is sealed and before refinement or delivery-quality
planning. The overlay verifies whether the plan contains executable grounding,
representation, computation, and claim controls. It does not decide the initial
route, mutate the plan, execute a workflow, or claim that future evidence is
already valid.

```text
request -> existing planner -> immutable workflow instantiation + digest
                             -> post-plan verification overlay
                             -> existing refinement and delivery-quality planning
```

The runtime seam is in `staged_routing.py`, after `instantiate_workflow(...)`
and before `build_workflow_refinement_cycle(...)`. Implement it as a pure
`build_post_plan_verification(...)` call bound to the exact instantiation
digest. When disabled, the current planner result must remain byte-equivalent.

This complements two existing controls:

- Pre-route quality freezes define what a good plan must achieve.
- Downstream artifact assessment evaluates evidence and outputs that actually
  exist after execution.

The new overlay asks a different question: *does this already-selected plan
contain proportionate, evidence-grounded, and maximally deterministic means to
produce and verify its intended claims?* `verification_ready` must never be
presented as `evidence_validated`.

## Non-interference invariants

1. The overlay is a sidecar keyed to `base_plan_digest`; it never rewrites,
   reroutes, reorders, or enriches the initial plan in place.
2. The canonical plan digest before and after verification is identical.
3. Findings refer to stable plan locations and propose repairs; the existing
   refinement lifecycle decides whether to apply them.
4. Failures are local. One unsupported claim does not invalidate unrelated
   grounded or exploratory nodes unless it breaks a route-critical dependency.
5. The verifier is route-only: no workflow execution, source retrieval,
   installation, network fallback, or undeclared state mutation.
6. Evidence content is inert data. Embedded instructions cannot change the
   plan, verifier policy, source authority, or acceptance criteria.
7. Reordering assertions/evidence or adding irrelevant evidence does not change
   logically unaffected findings or the canonical receipt digest.

## Typed representation model

### ClaimAtom

A material assertion planned for an output or decision:

- stable claim ID and exact plan/node/output location;
- normalized predicate plus subject, relation, object, population, specimen,
  intervention, comparator, outcome, and time qualifiers;
- assertion kind: `extracted_fact`, `deterministic_derivation`,
  `symbolic_consequence`, `statistical_result`, `scientific_synthesis`,
  `exploratory_hypothesis`, `user_constraint`, `planned_future_action`,
  `execution_status`, or `unknown`;
- claim posture: `observed`, `computed`, `associated`, `causal`, `hypothesis`,
  `recommendation`, or `unknown`;
- materiality, consumer, intended use, requested ceiling, and prohibited
  promotions.

User preferences, declared constraints, future actions, explicit placeholders,
and explicit hypotheses are typed; they are not forced into factual-claim
verification.

### EvidenceAtom

An addressable evidence object, never model memory:

- source identity, owner/issuer, class, release/version/date, content digest,
  authorization, retrieval snapshot, and independence cluster;
- exact locator: field, row/cell, page/section/span, API response path, artifact
  member, or code/result address;
- access class: full text, abstract, metadata, snippet, user statement, local
  contract, or authenticated run artifact;
- asserted predicate, applicability, source role, directness, authority basis,
  extraction mode, and prompt-injection quarantine state;
- support class: `direct`, `proof_derived`, `distributed`, `partial`,
  `contradicted`, `absent`, or `retrieval_only`.

### ComputationAtom

A planned deterministic, statistical, generative, or human operation:

- executable/provider identity, version, environment, permissions, input/output
  types and digests, parameters, seed, and numerical tolerance;
- determinism class: `pure`, `reproducible_seeded`, `stochastic_estimated`,
  `semantic_generative`, or `human`;
- estimand, assumptions, invariants, negative/edge fixtures, replication rule,
  and provider-unavailable behavior.

Reproducibility establishes replayability, not empirical truth.

### DerivationEdge

A typed transformation from evidence, computations, or prior claims to a new
claim. Record operation, assumptions, monotonicity, lossiness, verifier, and
which qualifiers survive. Every released derived claim requires closed
provenance over these edges.

### SourceAuthorityProfile

Authority is contextual, not one global prestige score:

| Assertion | Preferred authority | Important limit |
|---|---|---|
| local identity, configuration, execution | canonical contract or authenticated run artifact | a plan is not execution evidence |
| law, regulation, official requirement | issuing authority and version/effective date | commentary may explain, not establish obligation |
| package/API behavior and version | official documentation or registry | old reviews do not override current official releases |
| observed experiment or numerical result | primary study/data/report | applies only to tested design, population, and system |
| consensus or standard practice | systematic review, guideline, or standard | does not supply uncited primary numerical details |
| user preference or constraint | the user | does not establish an external biological fact |

Track authority fit, directness, timeliness, applicability, independence, and
conflict separately. “Official” is not automatically the most direct source for
a biological effect, and source count is not a truth vote.

### VerificationObligation

Bind a claim/node/edge to one method, exact pass condition, required inputs and
evidence, severity, failure consequence, re-entry owner, invalidation inputs,
and whether producer/evaluator separation is required.

### UncertaintyVector and GroundingMatrix

Do not collapse uncertainty into one confidence score. Preserve measurement,
sampling, model, stochastic, source-disagreement, applicability, and missing-
evidence uncertainty. The grounding matrix records each claim × evidence
relationship, authority/directness fit, contradiction, derivation, supported
ceiling, and disposition.

## Verification method router

Choose the least-flexible adequate method and record why a more flexible method
was unnecessary or required.

### Deterministic

Use for schemas, enums, identifiers, joins, units, hashes, versions, timestamps,
artifact presence, exact extraction, arithmetic, formula recomputation, set
relations, deduplication, DAG reachability, typed-port compatibility, provenance
closure, source-locator resolution, and inclusion/exclusion rules. A generative
judge must not decide an assertion already settled by an exact check.

### Symbolic or constraint based

Use for ontology/namespace compatibility, temporal or interval ordering,
mutually exclusive states, required-premise logic, authority/claim-ceiling
rules, and protocol constraints. Use `entailed`, `contradicted`, or `unknown`;
declare open/closed-world and boundary semantics; return an unsat core or
counterexample. Formal consequence is relative to encoded premises, not proof
of biological truth.

### Statistical or computational

Use for estimands, effect/prediction estimates, uncertainty, calibration,
sensitivity, multiplicity, robustness, and simulation. Require data geometry,
assumptions, provider/version, seed where relevant, and explicit result ceiling.

### Generative

Use only for semantic query expansion, candidate extraction, paraphrase
fidelity, source-role interpretation, bounded synthesis, rival explanations,
hypothesis formation, and critique. Candidate extracted facts remain provisional
until an exact locator/field check. The generation envelope contains allowed
evidence IDs, prohibited promotions, output schema, abstention behavior, and an
independent claim-fidelity review. Generation may propose structure or
hypotheses; it cannot manufacture evidence.

### Human

Reserve for value-laden tradeoffs, ambiguous applicability, unresolved
high-impact conflicts, and clinical, legal, regulatory, or ethical authority.

## Verification sequence

1. Seal the workflow-instantiation digest, accepted requirements, catalog/source
   snapshots, and verifier policy.
2. Compile material outputs into ClaimAtoms while preserving user constraints,
   prospective actions, hypotheses, and unknowns as distinct types.
3. Classify every operation by determinism class. Propose deterministic or
   symbolic replacement only where semantics are fully specified.
4. Compile claim-specific source inclusion, exclusion, role, directness,
   currency, authority, conflict-search, and stop policies before any retrieval.
5. Compile planned EvidenceAtoms and exact extraction/fidelity obligations.
6. Compile ComputationAtoms, derivation edges, provider preflights, invariants,
   tolerances, seeds, and negative/edge fixtures.
7. Build the GroundingMatrix, propagate claim ceilings, retain contradictions,
   and identify orphan claims or unverifiable derivations.
8. Apply bounded generative review only to unresolved semantic obligations.
9. Emit local dispositions: `pass`, `pass_with_caveat`, `revise_plan`, `defer`,
   `block`, or `inconclusive`, plus proposed patch operations and owners.
10. Append a user-facing reasoning event describing checks, evidence policy,
    remaining uncertainty, affected nodes, and next action without exposing
    hidden chain-of-thought.

## Claim ceilings

- Source field or raw artifact -> observed/descriptive only.
- Deterministic derivation -> computed conditional on inputs and rules.
- Observational/statistical result -> association, not causal effect.
- Randomized or credibly identified design -> causal only for its estimand,
  population, design, and assumptions.
- Perturbation/preclinical experiment -> response/mechanism only in the tested
  system; no automatic clinical efficacy.
- Review/guideline -> consensus/context, not uncited primary measurements.
- Search with no hit -> “not found under the frozen protocol,” not “does not
  exist” or “first ever.”
- Prediction performance -> tested predictive utility, not mechanism.
- Formal proof -> entailed under encoded premises, not universal empirical truth.
- Generative suggestion -> hypothesis only.

## Proportionate, non-paranoid control

Risk is determined from materiality, decision impact, irreversibility, claim
strength, and evidence gap—not from alarming topic words or citation count.

An exploratory hypothesis may pass as `proposed` when its provenance, evidence
basis, rivals, uncertainty, discriminating test, and prohibited factual
promotion are explicit. Lack of confirmatory proof is not itself failure.

Normally local, non-blocking caveats include a single source, preprint status,
narrow cohort, modest disagreement, stale noncritical context, and low-power
exploratory evidence. Local blocking defects include fabricated/non-resolving
sources, exact value or unit mismatch, unauthorized evidence, failed
deterministic recomputation, incompatible scope presented as direct support,
causal promotion from association, formal claims outside premises, and mutation
of the base plan.

Do not demand citations for user preferences, requested outputs, prospective
methods, recorded deterministic transformations, explicit placeholders,
declared unknowns, or properly labeled hypotheses. Block the smallest affected
claim or handoff. Search stops when each predicate is supported, explicitly
unresolved/contradicted, or the frozen budget is exhausted.

## Concrete cases

1. A table states 37 participants and 11 events: exact extraction passes; “12
   events” is contradicted without generative adjudication.
2. An abstract reports reduced marker expression in a cell line: a bounded
   paraphrase passes; patient benefit, sample size, or confidence intervals not
   present in the abstract remain unsupported.
3. An official package registry governs version 2.1; the primary paper governs
   its biological observation. Neither is globally more authoritative.
4. A planned differential-expression run is a valid prospective action; a
   statement that it completed is unsupported without a run artifact.
5. Dose at hour 0 plus collection required at 6–12 hours and observed at hour 4
   is protocol-inconsistent. With collection time absent, the result is unknown.
6. A weak association plus pathway background may support an exploratory
   mechanism lead with rivals and a discriminating assay; “mechanism established”
   is blocked.
7. A network-denied selected source remains selected but locally blocked; no
   similar database is silently substituted.
8. A generated novelty review may say “not identified in searched sources” only
   when the dated query, coverage, deduplication, and counterexample search are
   frozen; it may not say “first ever.”

## Reuse and integration constraints

The verifier should compose existing semantic responsibilities rather than
creating weaker duplicates. Candidate owners include
`deterministic-claim-anchor-compiler`, `source-result-fidelity-verifier`,
`claim-fidelity-verifier`, `evidence-directness-claim-gater`,
`provenance-rule-materializer`, `retrieval-schema-validator`,
`evidence-sufficiency-gate`, `formal-symbol-grounding-linker`,
`symbolic-rule-induction-governor`, `interpretation-control-algorithmizer`,
`methods-provenance-auditor`, `claim-ceiling-propagator`,
`citation-reference-linker`, `counterexample-miner`, and
`literature-adjudicator`. The deterministic kernel remains planner runtime code;
it is not disguised as a conversational skill.

`plan_stages()` does not currently receive the later external-source, external-
framework, or package-search receipts. Before claiming source-authority coverage,
introduce an immutable `verification_context` carrying only already-produced
planning receipts and their digests. Do not move network access or retrieval into
the verifier. The integration must preserve standalone-wheel operation and avoid
static imports from the host `catalog` tree.

## Implementation TODOs

The machine-readable backlog is
[`post-plan-evidence-verification-todos.json`](post-plan-evidence-verification-todos.json).

### P0 — contracts and non-interference

- **PPEV-001:** Define versioned overlay, ClaimAtom, EvidenceAtom,
  ComputationAtom, DerivationEdge, AuthorityProfile, UncertaintyVector,
  VerificationObligation, GroundingMatrix, assessment, and repair schemas.
- **PPEV-002:** Implement the pure post-instantiation hook and prove canonical
  plan digest preservation and no planner-store mutation.
- **PPEV-003:** Implement claim/output decomposition with requirement, consumer,
  node, source-turn, and terminal-artifact traceability.
- **PPEV-004:** Implement deterministic/symbolic/statistical/generative/human
  method routing with explicit reasons and prohibited fallbacks.
- **PPEV-005:** Implement contextual authority and claim-specific source-policy
  compilation frozen before retrieval.
- **PPEV-006:** Implement provenance closure, exact locator validation, grounding
  matrix construction, and claim-ceiling propagation.
- **PPEV-007:** Emit only local dispositions and proposed repairs; integrate them
  into refinement without in-place mutation.
- **PPEV-008:** Bind reviewed existing evidence, provenance, fidelity, directness,
  sufficiency, formal-grounding, and claim-ceiling skills to semantic obligations;
  keep the exact verification kernel in runtime code.
- **PPEV-009:** Define an immutable `verification_context` for existing external-
  source/framework/package planning receipts and preserve portable host ports.

### P1 — executable verification controls

- **PPEV-010:** Add deterministic adapters for registry membership, schemas,
  hashes, versions, typed joins, units, arithmetic, DAGs, artifacts, exact
  extraction, and evidence completeness.
- **PPEV-011:** Add computation receipts with environment/provider preflight,
  seed, tolerance, replication, and fixture/invariant policies.
- **PPEV-012:** Add contradiction and source-independence clustering so mirrored
  records cannot masquerade as corroboration.
- **PPEV-013:** Add the bounded generative envelope and independent fidelity
  verifier; prohibit new factual specifics outside allowed evidence IDs.
- **PPEV-014:** Add risk-proportional exploratory/confirmatory templates,
  anti-paranoia exemptions, bounded search, and local failure propagation.
- **PPEV-015:** Add selective invalidation for changes to the base plan,
  requirement, evidence/source release, method/version, parameters, authority,
  or source policy.
- **PPEV-016:** Add user-facing verification summaries and normalized reasoning-
  log events distinct from hidden reasoning and post-run evidence validation.
- **PPEV-017:** Make existing workflow refinement consume overlay findings and
  test specifications without treating the sidecar as new planning authority.

### P2 — symbolic reasoning, benchmarks, and release

- **PPEV-020:** Add symbolic adapter contracts for ontology, namespace, temporal,
  protocol, scope, and claim-ceiling constraints with unknown/unsat explanations.
- **PPEV-021:** Build `benchmarks/planner/post-plan-evidence-grounding/` with 24
  paired disclosed cases, mutation probes, and a separately governed sealed set.
- **PPEV-022:** Add non-interference integration tests proving that planner output
  is identical when verification is disabled, enabled-pass, caveated, or locally
  blocked except for the additive sidecar and downstream proposed repairs.
- **PPEV-023:** Add adversarial tests for fabricated citations, identity swaps,
  unit/value mismatch, abstract/full-text confusion, duplicated corroboration,
  prompt injection, causal overpromotion, search-absence overclaim, stale
  regulation, denied sources, and execution-state hallucination.
- **PPEV-024:** Add anti-paranoia tests ensuring user constraints, future actions,
  explicit hypotheses, deterministic transformations, and unknowns are not
  falsely blocked.
- **PPEV-025:** Report grounded material-claim rate, exact-anchor fidelity,
  unsupported-claim escape rate, claim-ceiling accuracy, deterministic-routing
  rate, conflict retention, repair locality, benign false-positive rate,
  latency, and cost.
- **PPEV-026:** Update standalone packaging, schemas/resources, planner README,
  lifecycle/profile documentation, capability maps, and release checks.

## Release thresholds

Non-compensatory thresholds for the disclosed deterministic corpus:

- 100% initial-plan digest preservation and prompt-injection invariance;
- zero fabricated IDs, locators, numbers, quotations, or execution states;
- 100% deterministic routing for exact-oracle cases;
- zero released claims above their oracle ceiling;
- zero silent evidence substitutions;
- 100% repeat and canonical-order determinism;
- 100% preservation of approved exploratory hypotheses as `proposed`;
- 100% localization of unknowns and repairs to affected claims/nodes;
- zero blocking false positives on explicit benign controls and at least 0.95
  specificity on the broader benign set; and
- every blocked material claim has an evidence-resolving, owned TODO.

Semantic synthesis metrics and human-reviewed oracles are reported separately;
lexical checks alone cannot certify semantic quality.
