<!--
SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>

SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
Neuro-symbolic AI Group

SPDX-License-Identifier: Apache-2.0
-->
# Lunar planner surface index

## Purpose

The planner needs one deterministic navigation view spanning the whole current
Lunar portfolio. It reuses canonical discovery surfaces and does not become
a catalog, registry, router, or execution authority.

The generated file is:

`selected-package://surface`

Build or verify it with:

```bash
.venv/bin/python scripts/repository/build_planner_surface_index.py
.venv/bin/python scripts/repository/build_planner_surface_index.py --check
```

## Source surfaces

- Effective scientific descriptors from the canonical `catalog/agents/` tree,
  plus planner descriptors used only for explicit internal control routes,
  through `catalog.registry.skill_descriptor`.
- Every top-level package under `catalog/workflows/` with an `__init__.py`.
- Executable workflow identity from `catalog/workflows/*/cli.py`.
- Every promoted universal subworkflow manifest under
  `catalog/workflows/public/subworkflows/manifests/`.

The generator reads package docstrings with `ast`; it does not import workflow
CLIs. It reuses the subworkflow safe loader and effective descriptor loader.

## Current contract

The index contains:

- `schema_version: lunar.planner.surface-index/v2`
- `authority: derived_navigation_only`
- a selection boundary requiring semantic review
- all catalog-agent skill rows and internal planner-control rows with scope,
  source, invocation posture, availability, and content digest
- all workflow package rows with kind, source, optional CLI target,
  availability, and digest
- all promoted planning subworkflow rows
- counts by scope and workflow kind

It includes instruction-only and unavailable capabilities so the planner can
explain boundaries, but those rows cannot advertise execution. Missing archive
skills are excluded because they are not effective Lunar descriptors.

## Workflow classification

- `named_executable_workflow`: a canonical package with `cli.py`; the target is
  recorded but never invoked by the index or planner profiles.
- `reasoning_flow_registry`: the ERFL mapping package.
- `subworkflow_registry`: the planning-only composition package.
- `planning_subworkflow`: one promoted typed manifest.
- `workflow_support_package`: a package without a public CLI, if one is added.

## Selection and authority boundary

Index lookup and `catalog.integrations.planner.routing` gather candidates only. The
`skill-reuse-critical-reasoner` must review complete relevant contracts before
reuse, gap, or composition decisions. An index row never proves:

- semantic fitness;
- permission to execute;
- observed workflow invocation;
- scientific evidence or claim support;
- admission of a proposed skill or workflow.

## Future extensions

Reverse report/component lineage, workflow manifests richer than current CLI
packages, external callable-level overlays, and atomic promotion are residual
capabilities. They must extend current descriptor and workflow surfaces rather
than introducing parallel authorities.
