<!--
SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>

SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
Neuro-symbolic AI Group

SPDX-License-Identifier: Apache-2.0
-->
# Workflow-first archetype reuse

## Objective

The planner should not rediscover a workflow by scanning hundreds of skills for
every request. Many research problems share stable evidence, analysis,
criticism, validation, and reporting structures even when the disease, dataset,
mechanism, or final decision differs. The planner therefore searches complete
workflow archetypes before expanding individual skill candidates.

An archetype is a versioned, parameterized workflow contract. It describes a
reusable problem geometry, ordered responsibilities, typed handoffs, evidence
and claim boundaries, required critics/validators, terminal artifacts, and
variation points. It is not directly executable until its slots are bound to
compatible canonical skills/workflows, sources, representations, and runtime
dependencies.

The goal is to maximize coherent reuse coverage, not the raw number of skills.
An archetype with unnecessary stages or weak handoffs ranks below a smaller
contract-complete path.

## Relationship to existing surfaces

The repository already contains complementary seeds:

- public workflows and reasoning-flow projections show validated concrete
  end-to-end and epistemic paths;
- `workflow-reference-scout` finds workflow families and local parallels;
- `workflow-skill-gap-planner` and the universal subworkflow validator rank
  reuse paths and reject incompatible handoffs;
- `agentic-workflow-designer` turns a selected family into typed agent/stage
  handoffs;
- `workflow-skill-gap-planner` classifies only the residual workflow slots as
  direct, composed, partial, or missing capability;
- the five current skill-set composition blueprints provide broad
  reader–reasoner–writer seeds.

The archetype layer unifies these as indexed reuse candidates. It does not
replace them and does not create a second canonical workflow tree.

## Retrieval cascade

After the need, outcome, discovery-success level, and catalog snapshot are
fixed, the planner follows this order:

1. **Exact workflow reuse** — select an active canonical workflow whose complete
   input/output and authority contract fits.
2. **Full archetype reuse** — retrieve and semantically rank parameterized
   end-to-end archetypes by problem structure.
3. **Sub-archetype reuse** — splice validated evidence-search, mechanism,
   transport, validation, or reporting modules into an existing workflow.
4. **Composition-blueprint reuse** — use a compatible curated or
   contract-derived reader–reasoner–writer path.
5. **Residual skill search** — inspect individual skill bodies only for
   unbound, incompatible, or intentionally revised archetype slots.
6. **External capability search** — search external frameworks only for
   residual computational/source gaps after local workflow-level reuse.

The planner expands the bodies of the top bounded archetype candidates and the
skills occupying affected slots. It does not read every skill in the catalog.

## Problem signature and matching

Each request is normalized into a workflow problem signature containing:

- decision object and intended downstream action;
- expected terminal artifact and addressable output components;
- input/data geometry, modality, unit of analysis, and longitudinal/spatial or
  cross-context structure;
- evidence acquisition strategy and source boundary;
- reasoning modes such as inductive pattern finding, abductive mechanism
  formation, model-based probing, contrast, refutation, transport, and ranking;
- required validation, counterpressure, external-validity, and claim ceiling;
- source, representation, dependency, privacy, authority, and runtime
  constraints; and
- success, stop/pivot, informative-negative, and provenance requirements.

Retrieval uses deterministic facets to shortlist candidates. Existing semantic
owners then rank the shortlist by outcome coverage, input/handoff compatibility,
evidence-boundary fit, validated reuse, adaptation cost, protected behavior,
and negative/non-trigger fit. Keyword or embedding similarity can nominate an
archetype but cannot authorize reuse.

## Archetype contract

Each canonical archetype manifest records:

- stable ID, version, status, family, title, and source lineage;
- problem signatures, triggers, non-triggers, and explicit exclusions;
- decision object, claim boundary, input/output contracts, and terminal
  components;
- ordered required and optional slots with one responsibility per slot;
- typed handoffs, dependencies, parallel groups, loops, stop/pivot rules, and
  allowed no-ops;
- required evidence, critic, validator, provenance, and release roles;
- slot binding constraints and known compatible skills, workflows, adapters,
  sources, representations, and external callables;
- variation axes and protected invariants;
- demonstrated workflow consumers, transfer fixtures, negative fixtures,
  maturity, and quality/provenance evidence; and
- owner, source digests, supersession, deprecation, and invalidation metadata.

An archetype may include alternative slot families—for example, literature
retrieval from several governed source adapters—but every instantiated path
must resolve one compatible owner and artifact contract before execution.

## Instantiation and controlled adaptation

`workflow-archetype-match.json` returns a bounded ranked shortlist and reasons.
For the selected candidate, `archetype-instantiation-plan.json` binds parameters
and slots. `archetype-delta.json` classifies every stage as:

- `unchanged_reuse`;
- `parameter_binding`;
- `skill_substitution`;
- `monotonic_skill_extension`;
- `adapter_or_representation_change`;
- `inserted_subworkflow`;
- `removed_optional_slot`; or
- `unresolved_gap`.

Reworking a skill is allowed when the archetype remains the best structural
basis. The current skill contract is preserved until a separately accepted,
monotonic creator-owned change passes its tests. A workflow-specific change is
kept in the instantiation unless transfer evidence justifies improving the
canonical archetype.

Archetype selection is never all-or-nothing. A useful 80-percent structural
match can anchor the plan while residual slots proceed through actual-body
reuse, source/representation, external-framework, and skill-gap decisions.

## Initial archetype collection

The first registry should normalize existing workflows, reasoning profiles, and
composition blueprints into the following candidate families. Their initial
status remains `candidate` until schemas, source lineage, bindings, and transfer
fixtures pass admission.

| Archetype | Stable reusable spine | Existing seed surfaces |
|---|---|---|
| `literature-evidence-adjudication` | question → governed search/retrieval → screening/extraction → evidence normalization → support/counterpressure → claim calibration → report | `literature-to-adjudicated-report`, bounded EBR |
| `mechanistic-hypothesis-pressure-test` | scope → pattern → abductive mechanisms → contextual model → model/contrast/refutation probes → calibrated ranking → next evidence | contextual-graph EBR, discovery-control, multisolver coherence |
| `omics-program-to-mechanism` | data contract/QC → feature or state program → pathway/module compression → mechanism → external evidence → validation → visual report | `omics-to-visual-report`, melanoma resistance stages |
| `resistance-combination-discovery` | treatment/context framing → resistance programs → targets → complementary interventions → pressure tests → ranked combinations → report | melanoma-resistance workflow, atlas-resistance-combination family |
| `cross-context-mechanism-transfer` | source/target contracts → representation alignment → shared circuit → contextual differences → transport/counterexamples → calibrated transfer decision | cross-tumor workflow, cross-context-circuit-ordering family |
| `target-therapy-prioritization` | candidate generation → target evidence → mechanism → pharmacology/exposure/safety → differentiation/biomarker → rank → next evidence | `knowledge-platform-to-hypothesis-card`, target-window and chemistry-readiness families |
| `cohort-biomarker-validity` | cohort/data contract → feature/model plan → internal evaluation → subgroup and calibration checks → external validity → methods/report | `cohort-to-validity-methods`, benefit-enrichment family |
| `perturbation-combination-design` | mechanism candidates → perturbational evidence → logical/dynamic models → synergy/antagonism → exposure/safety → experiment priorities | multisolver coherence and combination dependencies |
| `spatial-microenvironment-circuit` | spatial/data contract → cell states → interactions/circuits → exclusion or niche mechanism → cross-cohort/context check → intervention hypotheses | spatial-exclusion and metastatic-niche families |
| `longitudinal-state-transition` | timepoint contract → state trajectories → transition drivers → resistance/evolution hypotheses → intervention windows → follow-up | longitudinal state dependencies and resistance workflow stages |
| `analysis-to-validated-report` | released analysis artifacts → evidence/claim audit → narrative synthesis → figures/tables → render parity → release | contextual graph report, workflow report writers, report auditors |
| `workflow-output-diagnosis-and-repair` | output selector → retrospective lineage → reproduction/audit → causal localization → smallest repair → matched rerun → differential validation | planner refinement profile |

These are structural starting points, not frozen scientific recipes. Literature
adjudication, mechanistic pressure testing, external validity, provenance, and
report release can also be indexed as reusable sub-archetypes.

## Learning and promotion

Every completed workflow records archetype selection, slot bindings, delta,
tests, observed provenance, and outcome. A recurring instantiation difference
may become an archetype improvement only after multiple compatible consumers or
strong near/far transfer fixtures demonstrate that it is general rather than a
domain accident.

Promotion is atomic with the unified catalog transaction. Candidate archetypes
are searchable but non-executable; active archetypes are eligible planning
bases but still require concrete slot binding. Deprecation retains aliases,
consumers, migration guidance, and the last valid digest.
