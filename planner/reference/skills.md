<!--
SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>

SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
Neuro-symbolic AI Group

SPDX-License-Identifier: Apache-2.0
-->
# Lunar skill coverage

The adapted planner does not import, alias, or create the archive's proposed
skills. It dynamically covers every admitted scientific skill under
`catalog/agents/` through effective descriptors and every canonical workflow
through the generated surface index. Planner skills remain present only for
explicit internal control routes. Project-support skills are outside the
planner catalog.

## Current planning stack

- `workflow-reference-scout`: searches existing workflow families and local
  reference surfaces before invention.
- `skill-portfolio-navigator`: narrows the full catalog to a credible candidate
  packet.
- `skill-reuse-critical-reasoner`: reads complete skill bodies and owns the
  semantic reuse decision.
- `workflow-skill-gap-planner`: classifies direct, composed, partial, and absent
  coverage and produces implementation-grade TODOs.
- `pipeline-design-refinement-planner`: assembles new, extension, and
  refinement plans from the reuse packet.
- `run-inspector` and `artifact-inspector`: provide current evidence for
  extension and refinement.
- Project-support contract, conversational, test-coverage, workflow-health,
  and release-gate skills protect repository integration.

Candidate gathering reuses `catalog.integrations.planner.routing`; typed small compositions
reuse `catalog.workflows.public.subworkflows`. Neither surface executes a selected
skill or workflow.

## Complete coverage

Run:

```bash
.venv/bin/python scripts/repository/build_planner_surface_index.py
```

The generated
`selected-package://surface` contains all current
scientific skills from `catalog/agents/`, internal planner-control descriptors,
canonical workflow packages, and promoted planning subworkflows. It excludes
`project-skills/`. The index is deterministic and can be checked with `--check`.

## Ignored archive proposals

The archive's `CREATOR_CONTEXT.md` proposal packages were omitted from the
adapted tree because Lunar has no admitted skills at those paths. Their
former names do not appear as owners in the adapted workflow profiles.
The migration-only [`bioagents-reuse-map.json`](bioagents-reuse-map.json)
records why placeholders were not created.
