<!--
SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>

SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
Neuro-symbolic AI Group

SPDX-License-Identifier: Apache-2.0
-->
# Planner-level capability reasoning annotation plan

## Outcome

Add an optional, planning-only process that can inspect a new or changed skill,
tool, adapter, or external capability and produce a reviewable metadata package.
The package describes what the capability is for, how it reasons or transforms
information, what it depends on, and which licenses or terms govern it. It does
not execute the capability, change its source, or make a legal determination.

This is a design and implementation backlog. No annotation skill, runtime hook,
schema, or catalog projection is authorized by this document alone.

## Reuse boundary

The implementation must join existing authorities rather than inventing a
parallel taxonomy or catalog:

- `to_prism/taxonomy.json` is the canonical component taxonomy. An annotation
  binds its taxonomy ID, semantic version, and SHA-256 digest.
- `to_prism/src/to_prism/component_taxonomy.py` is the reference for facet
  cardinality, evidence, confidence, rationale, abstention, and ancestor rules.
- `docs/reasoning-flow-language.md` remains the authority for ERFL epistemic
  dependencies. ERFL reasoning codes are not a substitute for component facets.
- `catalog/schemas/skill-descriptor-v1.schema.json` and
  `catalog/registry/skill_descriptor.py` remain the skill discovery surface.
- `catalog/schemas/external-capability-record-v1.schema.json` remains the
  governed external-tool discovery surface.
- The standalone planner receives taxonomy snapshots and capability sources
  through read-only host ports. It must not import `to_prism` or crawl parent
  directories. A packaged fixture may support tests, but cannot become a second
  canonical taxonomy.

Annotations are additive overlays. Existing `SKILL.md`, `skill.yaml`, tool
records, hooks, catalog indexes, routing, and content digests are unchanged
until a separately authorized, reviewed promotion step consumes an overlay.
Reviewed host-side sidecars should live outside target packages, for example
under `catalog/contracts/capability-annotations/skills/<scope>/<name>.json` and
`catalog/contracts/capability-annotations/tools/<provider>/<tool>.json`. This
avoids making a target digest depend on an annotation that contains that digest.
The sidecar tree is an extension view, not a second registry or router.

The current repository has no root `LICENSE`, `LICENCE`, `COPYING`, or `NOTICE`
file. Consequently, repository location alone cannot support a known license;
skill licensing remains `unknown` unless closer or external evidence is found.

## Semantic model

### Target identity

Every request freezes a `CapabilityTarget`:

- `target_kind`: `skill`, `tool`, `adapter`, or `external_capability`;
- stable capability ID, scope, source locator, revision, and content digest;
- declared interface and source files included in the review boundary;
- annotation purpose: discovery, selection, composition, invocation review, or
  catalog promotion.

A changed target digest invalidates the annotation. Aliases never replace the
stable identity.

### Canonical taxonomy annotation

Annotations preserve the taxonomy's orthogonal facets. Each annotated unit has
exactly one `primary_family`; other facets follow their declared cardinality.
Only the most specific supported taxon is stored. Each assertion carries source
anchors, confidence, and a substantive rationale. Unsupported facets use
explicit abstention rather than guessed values.

The planner should normally annotate the capability contract as one unit and
split it into named operations when materially different subprocedures would
otherwise force a misleading `mixed` label. Workflow topology is inferred from
relations between units and is never copied onto every operation.

Classification must apply the canonical negative rules. In particular:

- typed inputs do not prove formal deduction or deterministic execution;
- an LLM or software call does not by itself establish computational warrant;
- a graph does not prove causal reasoning;
- supplied evidence is not retrieval;
- extractive transformation must preserve the source boundary;
- candidate production is not an inference archetype without an independent
  inferential license;
- calibration language does not prove probabilistic representation; and
- domain terminology does not prove mechanistic reasoning.

### Derived operational posture

For usability, the planner derives one coarse posture after the canonical
facets have been assigned:

- `deterministic`: the complete relevant procedure and environment support
  `execution_determinacy=deterministic`;
- `generative`: candidate production is an essential authored operation and the
  result remains materially open, stochastic, or underdetermined;
- `hybrid`: essential named subprocedures have different postures and their
  interface is explicit;
- `non_executing`: the capability supplies only documentation or procedural
  knowledge and has no executable operation; or
- `unresolved`: evidence cannot support a more specific posture.

This projection records its contributing facets and evidence. It never replaces
`reasoning_realization`, `execution_determinacy`, `constraint_regime`,
`computational_mechanism`, or `computational_character`. A symbolic generator
may be deterministic; a constrained LLM may remain underdetermined.

Composition operates over named material lanes and conditional branches. A
presentation-only title generator does not make a scientific kernel generative,
whereas a generative fallback makes the design potentially generative even if
one observed invocation did not take that branch. Human judgment,
non-generative stochastic computation, and opaque external execution remain
explicit; they are never coerced into the simple triad. Aggregate confidence is
bounded by the weakest critical lane, and licenses, taints, authority needs,
side effects, and claim ceilings are unioned or conservatively propagated—not
averaged away.

### Description and purpose

The annotation separates:

- what the capability does (`description`);
- why and when it should be used (`purpose` and positive applicability);
- when it should not be used (negative applicability);
- inputs, required context, outputs, side effects, and authority ceiling;
- epistemic ceiling: the strongest claim the output may support; and
- examples and counterexamples tied to the declared contract.

Generated prose is marked `model_inferred` until a reviewer accepts it. It must
not masquerade as authored capability metadata.

## Dependency model

Dependencies are typed graph edges, not free-form package names. Supported
kinds are skill, workflow, adapter, runtime, package/library, system binary,
model, external service/API, dataset/database, ontology/taxonomy, credential,
network, hardware, and human review. Each edge records:

- required, optional, or conditional status and its condition;
- build, runtime, test, data, review, or composition phase;
- version constraint or immutable revision when known;
- source locator and evidence basis (`declared`, `statically_discovered`,
  `runtime_observed`, `reviewed_inference`, or `unknown`);
- capability supplied, availability, fallback, and failure consequence;
- network, credential, privacy, side-effect, and authority implications; and
- linked license evidence and unresolved transitive dependencies.

The scanner is bounded to the frozen source bundle: manifests, lock files,
referenced scripts, `SKILL.md`, `skill.yaml`, `agents/openai.yaml`, tool records,
and nearby license/notice files. It performs no network calls, installation, or
arbitrary environment inspection. Planned use is never labeled observed use.

## License and terms model

Licensing is an evidence inventory, not legal advice. Separate records cover
source code, skill text/content, model weights, datasets, APIs/services,
connectors/adapters, and transitive dependencies. Each record carries:

- status: `declared`, `detected`, `inherited`, `conflicting`, `unknown`, or
  `not_applicable`;
- SPDX expression only when the evidence supports one, otherwise verbatim or
  custom terms with an exact source anchor;
- subject, scope, version/revision, source digest, and governing locator;
- obligations and restrictions such as attribution, notice, copyleft,
  non-commercial, research-only, no redistribution, or credentialed access;
- compatibility disposition for the intended annotation purpose; and
- reviewer, uncertainty, and remediation required before promotion.

Nearest-file scope and nested licensing take precedence over an assumed root
license. Missing, contradictory, custom, or purpose-incompatible terms block
promotion or invocation readiness, but do not erase the capability from
discovery.

## Planner skill set

Implement four narrowly scoped planner skills, coordinated by the first:

1. `capability-annotation-planner` freezes the target and purpose, inventories
   admissible sources, invokes the specialists, and returns a statusful package.
2. `reasoning-taxonomy-annotator` assigns canonical facets with evidence and
   abstentions, then derives the coarse operational posture.
3. `capability-dependency-license-annotator` builds the dependency graph and
   license/terms inventory without external execution.
4. `capability-annotation-critic` independently challenges unsupported facets,
   hidden dependencies, license scope, contradictions, and promotion readiness.

Keep `SKILL.md` instructions concise and discriminatory. Put the field contract
and decision tables in references; use deterministic scripts only for schema,
digest, graph, SPDX-shape, and taxonomy-cardinality checks. Generative semantic
classification remains reviewable and cannot be certified by schema validity.

## Artifacts and lifecycle

```text
explicit request
  -> frozen target + source inventory
  -> taxonomy annotation + abstentions
  -> dependency graph + license inventory
  -> independent critique
  -> draft | needs_input | extension_required | blocked | reviewed
  -> optional, separately authorized catalog projection
```

The proposed contracts are:

- `lunar.planner.capability-annotation-request/v1`
- `lunar.planner.capability-source-evidence/v1`
- `lunar.planner.reasoning-taxonomy-annotation/v1`
- `lunar.planner.capability-dependency-license-manifest/v1`
- `lunar.planner.capability-annotation-review/v1`
- `lunar.planner.capability-annotation-package/v1`
- `lunar.planner.capability-annotation-invalidation/v1`
- `lunar.planner.taxonomy-extension-proposal/v1`

`extension_required` is a discovery result only. It cannot silently add a taxon
or promote an annotation. `reviewed` requires an independent critic result,
zero unresolved hard contradictions, exact taxonomy and target digests, and a
human decision for material custom, conflicting, or restrictive terms.

Annotations become stale when the target content, taxonomy, dependency
manifest, license evidence, provider/model revision, or reviewed override
changes. Revalidation reports the invalidating difference; it never refreshes
evidence silently.

## Integration and compatibility

The journey is explicit and default-off. Ordinary direct-use, new-workflow,
extension, refinement, answer-trust, and workflow-economics requests retain
their current outputs and digests. The first implementation should expose a
read-only `ReasoningTaxonomyProvider` and `CapabilitySourceProvider`, plus an
in-memory implementation for standalone tests. No planner hook automatically
annotates all discovered capabilities.

A future catalog projection may enrich skill descriptors and external
capability records through reviewed overlays with field-level provenance. It
must not overload the existing skill `authority` field with reasoning posture,
and it must preserve unknown values rather than manufacturing completeness.

## Verification strategy

Forward tests should cover one deterministic parser, one underdetermined LLM
writer, one hybrid retrieval-and-synthesis capability, one documentation-only
skill, one external tool with credentials and custom terms, and one multi-step
capability that must be split into operations.

Adversarial cases must include typed-I/O determinism leakage, LLM-equals-
stochastic leakage, symbolic-equals-deterministic leakage, supplied-evidence-
equals-retrieval leakage, root-license inheritance across a nested license,
unresolved transitive dependencies, dependency cycles, alias collisions,
generated prose presented as declared metadata, taxonomy digest drift, stale
target digests, and a proposed unknown taxon.

Promotion requires schema and digest checks, taxonomy cardinality/ancestor
validation, dependency-graph validation, explicit unknown/abstention checks,
independent semantic review, standalone wheel verification, existing planner
regression tests, and a zero-diff assertion while the feature is disabled.

## Definition of done

The implementation is complete only when the four skills, strict contracts,
ports, validators, fixtures, adversarial benchmark, documentation, and
invalidation path exist; default-off behavior is proven; skill and tool targets
share one normalized contract without losing source-specific fields; and no
annotation can be called reviewed without evidence-complete taxonomy,
dependency, license, and critic receipts.
