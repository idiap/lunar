---
name: workflow-skill-gap-planner
description: Turn a workflow description and a candidate skill packet into an explicit reuse-vs-gap plan with self-contained TODOs, distinguishing direct reuse, composition work, catalog problems, and true capability gaps.
---
<!--
SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>

SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
Neuro-symbolic AI Group

SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
Neuro-symbolic AI Group

SPDX-License-Identifier: Apache-2.0
-->

# Scientific Workflow Skill Gap Planner

Use this after the portfolio has been narrowed by `skill-portfolio-navigator` or `workflow-reference-scout`, and after `skill-reuse-critical-reasoner` has produced or requested a semantic reuse review.

## Goal

Produce an implementation-grade plan that is explicit about what already exists, what needs refinement, and what genuinely needs to be created.

The gap decision must come from content-based skill reading, not from keyword absence. A step is a true gap only after the relevant skill bodies have been reviewed for semantic fit and composition potential.

## Required Classifications

For each required workflow step, classify the local state as:

- `direct_reuse`
- `composed_reuse`
- `partial_reuse`
- `no_local_match`

Then classify each remaining problem as:

- `catalog_gap`
- `composition_gap`
- `true_capability_gap`

## Output Contract

Emit one `workflow_capability_plan` with:

- `workflow_objective`
- `required_workflow_steps`
- `reuse_plan`
- `required_skill_refinements`
- `new_skill_gaps`
- `external_search_tasks`
- `critic_and_test_requirements`
- `semantic_reuse_basis`
- `self_contained_todos`

Each TODO should be self-contained and state:

- `goal`
- `files_or_surfaces`
- `expected_outputs`
- `done_when`

## Rules

- Prefer refinement and composition over new skill creation.
- Do not declare `true_capability_gap` from search failure alone.
- If a broad orchestrator and specialist skill both apply, record the specialist as a mandatory companion rather than hiding it inside the broad route.
- Require explicit critic and validation layers for any workflow that produces scientific claims.
- If a missing capability might be available externally, create an `external_search_task` instead of guessing.
