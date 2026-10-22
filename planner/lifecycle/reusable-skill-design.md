<!--
SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>

SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
Neuro-symbolic AI Group

SPDX-License-Identifier: Apache-2.0
-->
# Evidence-backed reusable skill design

## Objective

Every justified skill creation or material update should produce the broadest
coherent capability that can be reused across real contexts. Universality is a
design direction, not permission to create vague catch-all skills. The planner
must maximize reuse while preserving one independently triggered reasoning
responsibility, one primary output, precise routing, typed contracts, and the
domain constraints that make the result correct.

## Reuse-scope ladder

The planner records the highest evidence-supported scope:

1. `instance_bound` — tied to one unavoidable input, source, or output form;
2. `workflow_family_reusable` — reusable by multiple workflows with the same
   reasoning responsibility and handoff contract;
3. `domain_reusable` — reusable across oncology problems after context is
   supplied through typed inputs or references;
4. `cross_domain_reusable` — independent of oncology-specific semantics and
   supported by transfer evidence outside the originating domain.

The target is the highest level that preserves routing precision and semantic
correctness. A broader label requires broader evidence. Unsupported claims of
universality block acceptance rather than becoming aspirational metadata.

## Prospective reuse design

Before assembling a Codex skill-creator context packet, the planner produces a
`skill-reuse-design-assessment.json` for every proposed skill create or update.
It records:

- invariant reasoning responsibility and primary output;
- originating use case and incidental details that must not enter the core;
- stable input/output contracts and explicit variation axes;
- candidate consumers from distinct workflows and the typed handoffs they use;
- intrinsic domain constraints, portable policy parameters, and required
  source/framework adapters;
- alternatives: reuse an existing skill, extend an existing skill, create a
  reusable core plus adapters, create a narrower skill, or create no skill;
- selected reuse scope, supporting examples, counterexamples, exclusions, and
  residual portability limits;
- routing-collision, abstraction-tax, dependency, and correctness risks; and
- transfer fixtures and catalog metadata required to substantiate the scope.

For a no-skill-change plan, the artifact is an explicit no-op with the reuse or
composition decision that made authoring unnecessary.

## Design rules

- Generalize around an invariant decision and output contract, not around
  shared words in the originating requests.
- Parameterize context, cohort, disease, source, evidence policy, thresholds,
  and rendering choices when they vary without changing the responsibility.
- Keep source- or framework-specific mechanics in typed adapters when the core
  reasoning can remain independent. Keep them in the core when removing them
  would make the contract misleading.
- Prefer composition of atomic skills over a universal skill that absorbs
  routing, acquisition, reasoning, validation, and presentation.
- Do not bake one workflow's ordering, report section, tumor type, dataset,
  package, or example wording into the core unless it is an intrinsic trigger
  or safety invariant.
- Use progressive disclosure for context-specific details. Add a resource only
  when it changes decisions for a real mode or avoids repeated implementation.
- Keep descriptions discriminating. Broader applicability must not make the
  skill trigger on unrelated requests or overlap ambiguously with catalog
  neighbors.
- Prefer stable schemas and capability-based dependencies over repository-path
  coupling. Record unavoidable platform, source, license, and authority limits.

## Validation

A claimed reusable skill is tested with:

- the originating case;
- at least one near-transfer case from another workflow;
- a farther-transfer case when `domain_reusable` or `cross_domain_reusable` is
  claimed;
- negative and ambiguity cases that must not route to the skill;
- typed-contract and consumer-canary checks; and
- a specialization check showing that parameterization or adapters do not
  erase necessary domain constraints.

One example cannot establish universality. When transfer fails, the planner
narrows the declared reuse scope, factors a stable core from adapters, or sends
evidence to Codex `skill-creator` for bounded revision. It must not patch the
skill body itself.

## Closure rule

A new or materially changed skill cannot be promoted unless its declared reuse
scope, variation axes, exclusions, consumers, and transfer evidence agree
across the creator packet, returned skill, catalog index, tests, and workflow
bindings. The planner rejects both needless specialization and unsupported
genericity.
