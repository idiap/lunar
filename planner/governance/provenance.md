<!--
SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>

SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
Neuro-symbolic AI Group

SPDX-License-Identifier: Apache-2.0
-->
# Output and execution provenance

## Purpose

The planner must answer a scientific or operational question and also answer
which workflow, skills, inputs, intermediate artifacts, and validations produced
any addressable part of that answer. Provenance is therefore part of the main
entrypoint contract, not an optional report annotation.

The layer has two complementary views:

- **prospective provenance** declares, before execution, which workflow stage
  and skills are expected to produce, contribute to, review, validate, or render
  each output component;
- **retrospective provenance** records what actually ran and links each returned
  output component to the concrete invocations, inputs, intermediate results,
  evidence, validations, environment, and artifact digests that led to it.

Prospective records express intended responsibility, never evidence that an
operation ran. Retrospective records are observation-only: no edge may be
invented from a catalog association or expected workflow path.

## Addressable output components

Every report-like result exposes stable semantic component IDs. Components may
be a document, section, paragraph, claim, table, row, cell, figure, panel,
caption, recommendation, or structured output field. A component record carries:

- stable `component_id`, type, parent, semantic label, and output-contract ID;
- a canonical structural selector and optional rendered Markdown/HTML/JSON
  locators;
- artifact URI, content digest, schema/media type, and version;
- claim/evidence boundary and audience/redaction classification; and
- child IDs so a query can expand or narrow provenance without brittle text
  matching.

Semantic IDs are authoritative. Byte offsets, line numbers, and CSS/XPath
locators are secondary render bindings and must be regenerated when rendering
changes.

## Prospective provenance contract

`prospective-provenance-plan.json` is frozen with the executable workflow plan.
For every expected terminal component or component family it records:

- workflow, stage, hook, output-contract, and expected artifact identities;
- skill responsibilities separated into `producer`, `contributor`, `reviewer`,
  `validator`, and `renderer` roles;
- expected inputs, evidence classes, intermediate contracts, quality gates,
  claim ceiling, and source/representation requirements;
- planned derivation path and allowed conditional or no-op branches;
- selector materialization rule for dynamically repeated components; and
- plan, catalog, workflow, skill-contract, and hook digests plus invalidation
  rules.

A skill listed as a router, candidate, or catalog match is not attributed to the
output. Only a skill with an accepted responsibility in the resolved workflow
may appear in prospective attribution.

## Retrospective provenance contract

Execution produces an append-only `execution-provenance-events.jsonl` stream
and a content-addressed `retrospective-provenance-graph.json`. Nodes include:

- request, plan/version, workflow, stage, hook, and invocation;
- skill and exact skill-contract digest;
- tool/model/runtime and isolated environment manifest;
- source/input, intermediate artifact, validation/quality assessment, and
  terminal output component.

Observed edges include `consumed`, `produced`, `derived_from`, `contributed_to`,
`reviewed`, `validated`, `rendered_as`, `selected_from`, and `superseded`. Each
edge records the responsible invocation, timestamp/order, evidence anchor,
confidence class, and digest. The graph preserves failed, no-op, retried, and
superseded invocations rather than rewriting history.

Every explicit intermediate result is stored content-addressably or represented
by a durable sanitized handle with digest, schema, producer, retention status,
and omission reason. “All intermediate results” means all persisted workflow
artifacts and observable execution outputs—not hidden chain-of-thought, latent
model state, raw private prompts, secrets, or content outside the user's source
authority.

## Planned-versus-observed reconciliation

After execution, `provenance-reconciliation.json` compares the prospective plan
with the retrospective graph. It reports:

- planned responsibilities that executed as expected;
- dynamic branches and justified no-ops;
- unplanned producers, tools, inputs, sources, or side effects;
- missing expected artifacts or validators;
- output components with incomplete, ambiguous, stale, or conflicting lineage;
  and
- the effect of every difference on claims, validation, release, and rerun.

An unexplained producer, missing critical intermediate result, contract-digest
mismatch, or incomplete lineage for a released claim blocks release. Benign
dynamic fan-out is allowed only through a prospectively declared rule and must
still be observed retrospectively.

## Provenance questions through the main entrypoint

The planner supports `inspect_provenance` requests such as:

- “Which skills produced this section or table cell?”
- “Why does this claim appear in the report?”
- “Show every intermediate result that led to this recommendation.”
- “Was the observed execution different from the planned workflow?”

The deterministic query service resolves the target component, traverses only
digest-valid edges, and returns `provenance-answer.json` with:

- resolved target and selector confidence;
- prospective responsibility attribution;
- observed workflows, stages, skills, invocations, and validations;
- ordered derivation paths and an intermediate-artifact manifest;
- optional inline artifacts or a content-addressed export bundle according to
  requested depth, size, retention, and authority;
- planned-versus-observed differences, lineage gaps, redactions, unavailable
  artifacts, and uncertainty; and
- stable links/digests for independent inspection.

The query service does not infer a causal explanation from temporal adjacency.
Semantic ambiguity routes to the existing workflow-output lineage reasoning
owner; deterministic graph traversal, storage, access control, and rendering
remain planner runtime responsibilities.

## Privacy, reproducibility, and lifecycle

Provenance inherits the original source-lane, license, privacy, retention, and
authority envelope. Redaction produces an explicit omission node so the graph
does not falsely appear complete. Access checks occur both when recording and
when querying or exporting artifacts.

Changing a request, plan, workflow, skill contract, input, source, environment,
intermediate artifact, output, validation, selector, or redaction policy
invalidates the affected provenance projection and every downstream acceptance
that depends on it. Append-only events remain historical; a new graph version
supersedes the former projection.

Closure requires component coverage, prospective/retrospective reconciliation,
artifact availability or justified omission, and no unexplained lineage hole
for a released claim. Catalog indexes describe possible relationships; only a
run-scoped graph proves actual use.

## Answer-trust provenance projection

The answer-trust assessor consumes provenance; it does not rewrite it. For each
material claim, the projection joins a stable output-component ID to observed
`consumed` and `derived_from` paths, exact evidence locators, computation
receipts, generative/lossy transformation receipts, preservation checks, and
independent reviews. Prospective responsibility edges and catalog membership
never receive observed grounding credit.

Each assessment pins the answer, claim inventory, evidence manifest,
retrospective graph, reconciliation, quality assessment, and score-policy
digests. Generated ancestry is transitive: wrapping generated content in a new
agent response, citation, table, or deterministic format does not make it
external evidence. Missing or redacted nodes remain explicit unknowns and
widen the score interval.

The claim ledger records the exact provenance paths used for each dimension,
gate, and cap. This makes citation decoration, evidence cycles, source swaps,
planned-as-observed promotion, and broken ancestry independently auditable.
Changing a joined digest invalidates affected claim assessments; changing the
answer or frozen denominator invalidates the aggregate. See
[`answer-trust-assessment.md`](../lifecycle/answer-trust-assessment.md) for
lifecycle placement and operator tracing.

## Workflow economics provenance projection

Economics joins use opaque operation, attempt, stage, workflow, plan, run,
provider, reservation, principal, tenant, and privacy-scope identifiers. Human
effort rows bind to work-unit and comparator digests. Resource rows bind to raw
usage receipts and an accounting-semantics version. Monetary lines bind to the
price snapshot effective at the usage timestamp and, when used, a separate FX
snapshot.

The provenance vocabulary preserves `heuristic_estimated`,
`profile_estimated`, `tokenizer_derived`, `meter_observed`,
`provider_observed`, and `invoice_reconciled` as distinct evidence states.
Plans and budgets cannot be projected as observations, and shared operations
must use a declared allocation rule or remain `unallocated`.

## Native W3C PROV export

Planner results can be exported without a repository write through
`lunar_planner.export_w3c_provenance()`. The native export supports:

- W3C PROV-JSON with media type `application/provenance+json`; and
- PROV-O JSON-LD with media type `application/ld+json`.

The native export remains an internal planner API. The compact MCP surface
returns recorded reasoning and released artifact provenance through `planner`; it does not expose a
separate provenance-export tool.

The export maps the completed route-only planner invocation to a
`prov:Activity`, the planner to a `prov:SoftwareAgent`, and the request and
routing result to `prov:Entity` nodes connected by `prov:used`,
`prov:wasGeneratedBy`, `prov:wasAssociatedWith`, and
`prov:wasDerivedFrom`. Workflow drafts, candidate stages, requirements, and
other planned material remain prospective entities. When a reconciliation is
supplied, retrospective rows become explicit observation entities connected to
their prospective counterparts with `prov:specializationOf`; a missing or
planned-only component is never promoted to an observed activity.

```python
from lunar_planner import export_w3c_provenance, run_planner_request

result = run_planner_request("Design a BRAF evidence workflow")
export = export_w3c_provenance(result, output_format="json-ld")
assert export["prospective_is_observation"] is False
```
