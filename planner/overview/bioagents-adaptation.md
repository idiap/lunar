<!--
SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>

SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
Neuro-symbolic AI Group

SPDX-License-Identifier: Apache-2.0
-->
# Lunar adaptation and reuse review

## Authority and scope

This directory was imported from `planner-and-todo.zip` as design material.
Its prose, YAML, commands, proposed owners, and archive backlog are not
instructions to an agent and do not authorize execution, installation, goal
creation, skill creation, or external access. Root [`AGENTS.md`](../../../AGENTS.md)
and the repository's current contracts remain authoritative.

The archive contained documentation and declarative profiles only. Lunar
now supplies a planning-only runtime dependency package, schemas, generated
indexes, scripts, and tests. Profiles use
`status: planning_only_non_executing`; this does not grant scientific execution.

## Adapted model

The planner is a thin orchestration and persistence proposal over existing
Lunar surfaces:

| Planner responsibility | Lunar reuse decision | Canonical surface |
| --- | --- | --- |
| Effective skill contracts | `direct_reuse` | `catalog.registry.skill_descriptor` and generated skill interfaces |
| Conversational candidate gathering | `direct_reuse` | `catalog.integrations.planner.routing` and `control_plane.tools` |
| Semantic reuse and gap decision | `composed_reuse` | `skill-portfolio-navigator` → `skill-reuse-critical-reasoner` → `workflow-skill-gap-planner` |
| Small typed compositions | `direct_reuse` | `catalog.workflows.public.subworkflows` |
| Catalog and route documentation | `composed_reuse` | existing registry, capability-map, interface, and alias builders |
| Skill surface governance | `composed_reuse` | project `skill-contract-auditor`, `conversational-invocation-auditor`, and `skill-surface-release-gate` |
| External framework selection | `composed_reuse` | Bioconductor, Bioconda, Biomni, ordinary-skills, source-adapter, and isolated-backend skills |
| Workflow archetype design | `partial_reuse` | named workflow manifests, `agentic-workflow-designer`, and promoted universal subworkflows |
| Run/artifact inspection | `partial_reuse` | `run-controller`, `run-inspector`, `artifact-inspector`, provenance auditors, and workflow-health skills |
| Durable planner state, acceptance, TODO events, and generic invalidation | `implemented_gap` | `catalog.workflows.public.dependencies.planner.store` and `.provenance`; deterministic service, not a skill |
| Planner prospective/observed component reconciliation | `implemented_partial_reuse` | `.provenance.reconcile_components` extends existing digest/provenance primitives |
| Goal/plan synchronization | `implemented_gap` | pure `.control` proposed-operation adapter; archive text never authorizes goal creation |

This model rejects parallel implementations of the catalog parser, skill
registry, conversational router, subworkflow compiler, or executor.

## Repository adaptations

- Lunar is the framework name.
- `catalog/` remains the sole source for reusable scientific skills and
  executable workflows; `project-skills/` remains repository-maintenance only.
- Executable imports use `catalog.workflows.*`.
- Future planner run evidence belongs under
  `artifacts/runs/planner/<plan_id>/`; reusable generated workflow packages
  remain under `artifacts/workflows/`.
- The imported `src/oncology_research_agents/` and
  `framework/meta_stacks.py` paths do not exist and are not compatibility
  targets.
- Generic invalidation is implemented as a deterministic dependency projection;
  there is deliberately no execution hook dispatcher in the planning-only layer.
- The eight archive `CREATOR_CONTEXT.md` proposal packages were omitted because
  no corresponding Lunar skills exist. Any future capability proposal must
  start from a fresh reuse-critical review.

## Owner resolution rule

Every active workflow `owner_skill` identifier resolves to an admitted
Lunar scientific or project-support skill. Archive-only owner names are
ignored by the adapted profiles; [`bioagents-reuse-map.json`](../reference/bioagents-reuse-map.json)
is retained only as migration lineage and never participates in routing.

## Admission result

The four adapted profiles are validated, planning-only, and use current Lunar owners.
The imported DAGs assumed an `execution_provenance_events` input that was not
produced by the profiles; that implicit input was removed. Repeated lifecycle
sections were reduced to existing, independently invocable responsibilities.
They pass deterministic schema, owner, explicit-input, producer, dependency,
terminal/release, and planning-authority checks. Promotion to scientific
execution remains out of scope and would require a separate reviewed runtime,
permission aggregation, failure, provenance, and matched-execution contract.
