---
name: pipeline-design-refinement-planner
description: Drive workflow pipeline design and refinement from a clean context by combining AGENTS navigation, portfolio reuse discovery, gap separation, external analytical scouting, and implementation-grade TODO generation.
---
<!--
SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>

SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
Neuro-symbolic AI Group

SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
Neuro-symbolic AI Group

SPDX-License-Identifier: Apache-2.0
-->

# Scientific Pipeline Design Refinement Planner

Use this when we need a full planning pass for a new workflow or a major revision of an existing workflow pipeline.

## Read First

1. `AGENTS.md`
2. `docs/agents-capability-map.md`
3. any workflow-specific planning document under `docs/`

Then route through:

1. `skill-reuse-critical-reasoner`
2. `skill-portfolio-navigator`
3. `workflow-skill-gap-planner`
4. `external-analysis-scout` only if a true gap or current-state need remains

## Goal

Produce a pipeline design or refinement plan that is capability-aware, test-aware, and critic-aware before implementation starts.

The reuse decision must be content-based. Route and registry lookup may gather candidates, but the final mandatory-skill and true-gap decisions should be made by `skill-reuse-critical-reasoner` through a `codex exec` semantic review of candidate `SKILL.md` bodies and relevant artifacts.

## Output Contract

Emit one `pipeline_design_refinement_plan` with:

- `workflow_objective`
- `workflow_family`
- `design_geometry`
- `best_existing_skills`
- `required_refinements`
- `new_capability_gaps`
- `external_search_tasks`
- `critic_layers`
- `validation_layers`
- `self_contained_todos`

## Rules

- Start from reuse, not invention.
- Start from a `reuse_critical_packet`, not keyword matches.
- Keep the plan at the level of pipeline modules, artifacts, and skill responsibilities.
- Include the writer, critic, and evidence layers that keep the workflow package scientifically usable.
- If the analysis may need fresh external tooling or datasets, record that explicitly instead of silently assuming the local stack is enough.
