<!--
SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>

SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
Neuro-symbolic AI Group

SPDX-License-Identifier: Apache-2.0
-->
# Planner dependencies

This package implements Lunar planning support without becoming an
executable scientific workflow.

- `contracts.py`: strict YAML, planner JSON schemas, owner/handoff/profile
  admission.
- `entrypoint.py`: compatible public route-only planner boundary.
- `staged_routing.py`: request framing, unified retrieval, adjudication,
  evidence-aware dialogue reduction, semantic requirement decomposition, typed
  workflow drafts, binding, preflight, decision-aware elicitation,
  conversation-aware capability gaps, final workflow instantiation, proposed
  skill test specifications, failure diagnosis, minimum-fix planning, bounded
  execution-evidence refinement,
  continuation, and sealed handoff.
- `post_plan_verification.py`: pure, digest-bound verification of an already
  established plan's grounding, deterministic/symbolic controls, claim
  ceilings, and proportionate exploratory posture; it emits an additive
  planning sidecar and cannot execute or mutate the plan.
- `archetypes.py`: derived uncovered reusable structures.
- `store.py`: confined append-only versions, TODOs, and acceptance evidence.
- `provenance.py`: prospective-versus-observed reconciliation, invalidation,
  and native deterministic W3C PROV-JSON / PROV-O JSON-LD export.
- `next_steps.py`: suppress-or-suggest closure assessment and one concrete,
  authority-bounded next action derived from the current planner state.
- `delivery_package.py`: completion-gated deterministic ZIP delivery of
  generated files, integrity manifests, and W3C provenance descriptors.
- `control.py`: pure proposed Codex goal/plan operations with explicit authority.
- `benchmark.py`: explicit no-op or bounded paired skill-benchmark manifests;
  never a subprocess runner.
- `report_benchmark.py`: deterministic, route-only evaluation of realistic
  report-level planner requests with preserved expert-review oracles.
- `external_reuse_benchmark.py`: blind workflow-extension evaluation that
  requires observable local, Bioconductor, and Biomni resource awareness.

The package reuses effective skill descriptors, MCP routing, canonical workflow
packages, promoted subworkflows, and shared provenance hashing. It does not
execute skills or workflow CLIs, use the network, install dependencies, mutate
catalog contracts, create goals, or infer authority.

New-workflow, extension, and refinement profiles apply the packaged
`post_plan_reasoning_verification` overlay before their downstream release,
test, or health review. Direct-use intentionally omits it. A passing overlay
means that the plan is verification-ready; it is not evidence that any
prospective computation, retrieval, or scientific claim has been executed or
validated.

Verify the integrated layer with:

```bash
.venv/bin/python scripts/repository/check_planner_contracts.py --check
.venv/bin/python -m pytest -q tests/planner
```

Five-turn correction, input carry-forward, implicit composition, question
history, typed-edge, gap-retraction, and schema conformance tests live in
`tests/planner/test_planner_dialogue_state.py`.

The 20-case melanoma liver-metastasis suite and its isolated report fixture are
documented in
`benchmarks/planner/melanoma-liver-metastasis-report-needs/README.md`.
The complementary blind external-reuse suite is documented in
`benchmarks/planner/blind-external-reuse/README.md`.
`tests/planner/test_planner_real_benchmarks.py` runs both suites against the
real entrypoint; oracle-shaped evaluator stubs are not accepted as planner
regression coverage.
