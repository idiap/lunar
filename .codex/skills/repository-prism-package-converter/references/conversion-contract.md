<!--
SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>

SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
Neuro-symbolic AI Group

SPDX-License-Identifier: Apache-2.0
-->
# Complete conversion contract

Use this contract while mapping source workflows to PRISM and while reviewing a conversion. The terms MUST, MUST NOT, SHOULD, and MAY are normative.

## Repository boundary

One source repository produces one archive and one package key. The archive may contain many PRISM projects and workflows. Do not split packages by workflow, backend, skill family, or data-source family unless the user explicitly changes this rule.

Inventory all executable workflow surfaces, including declarative graphs, orchestrators, command registries, CI entrypoints, runtime adapters, backend loops, and nested workflows. Classify each as:

- `converted`: fully represented and runnable;
- `excluded`: outside the user-approved scope, with a reason;
- `blocked`: cannot be converted faithfully, with the missing authority or dependency identified.

The package catalog MUST account for every discovered workflow. Unsupported workflows fail the conversion; they are not silently reduced to documentation.

## Semantic preservation

For every converted workflow preserve:

- input fields, types, validation, defaults/examples, and confidentiality/network controls;
- ordered stages and named reasoning occurrences;
- branches, loops, retry bounds, stop conditions, and failure propagation;
- model calls and their typed outputs;
- local skill calls and data-source reads;
- native execution, backend versions, commands, timeouts, stdout/stderr, and receipts;
- produced artifacts and provenance links;
- review, consistency, source-fidelity, and promotion gates;
- terminal output type and rendered report meaning.

Keep three provenance levels distinct:

- package declarations say which skills and data sources are available;
- workflow contracts say which agent activations and source reads are required;
- run receipts say what actually executed or was read.

The latter two MUST match for every successful representative run. Availability alone
is never execution evidence.

Every material binding MUST execute the linked implementation. The strings `fixture`, `placeholder`, `not_executed_by_structural_fixture`, `native implementation not executed`, `fake handler`, and equivalent behavior are forbidden in runnable paths and representative inputs.

## Source-report compatibility

When a workflow has an associated repository report, the conversion MUST apply the
`repository-prism-report-compatibility` skill. Freeze the source report bytes and digest,
map every material source surface, and preserve report purpose, information architecture,
claims, limitations, provenance, navigation, and epistemic status.

Both the reviewed reasoning graph and material graph MUST terminate in a real
`prism.reporting.report.Report` through the same terminal `typed_report` occurrence.
Their occurrence sequences MUST agree exactly. The export public output type and Lunar
report contract MUST use the canonical `prism.reporting.report.Report` name. A native
layout object, Markdown string, HTML file, or JSON wrapper is a compatibility artifact,
not a substitute terminal type.

Before release, run the companion deterministic validator against the exact source and
generated report digests, and complete an independent evidence-bound semantic assessment.
Every associated report must pass both gates and rendered-UI inspection. Similar headings
or lexical overlap alone do not establish semantic compatibility.

## PRISM project layout

Each project SHOULD contain:

```text
projects/<workflow-id>/
|-- conversion/
|   |-- source-evidence.json
|   |-- workflow-architecture-plan.json
|   |-- generation.json
|   `-- hook-coverage.json
`-- prism_project/
    |-- main.prism
    |-- reasoning.prism
    |-- reasoning_api.prism
    |-- reasoning_materialization.prism
    |-- material_api.prism
    |-- materialization.prism
    |-- material_main.prism
    |-- occurrences.prism
    |-- relations.prism
    `-- generated/*.prism
```

Use additional files when required; do not create empty files solely to match this layout. `main.prism` exposes the complete reasoning workflow. `material_main.prism` is the host-executed entrypoint and MUST invoke the complete reasoning path.

## Lunar runtime registration

Place exactly one single-line JSON object after `# lunar-runtime:` in each material entrypoint. It MUST declare:

- stable runtime `id` and PRISM workflow `declaration`;
- `entry_argument` and a closed JSON `input_schema`;
- non-empty defaults or examples for all required UI fields;
- `output_schema`;
- `prepare_hook`, `execute_hook`, and `verify_hook` as explicit Lunar runtime bindings;
- metadata with `description`, `model_required`, required host capabilities, and timeout;
- `metadata.reasoning_required: true` for reasoning workflows;
- `metadata.reasoning_contract` with the workflow name and every required occurrence name;
- `metadata.provenance_contract` with an ordered `agent_invocations` array and a
  `required_source_reads` array;
- `metadata.completion_contract` as described below.

Provenance contract example:

```json
{
  "agent_invocations": [
    {
      "agent_name": "hypothesis_agent",
      "workflow_occurrence": "hypothesis",
      "activated_skill_ids": ["kb-abduce"]
    }
  ],
  "required_source_reads": [
    {
      "resource_id": "mathematics-kb",
      "source_local_identifier": "fixed-point-theorems"
    }
  ]
}
```

An empty `required_source_reads` array is correct when the workflow consumes no source.
Do not list every packaged source. An empty `agent_invocations` array is allowed only
when the material workflow genuinely invokes no PRISM agents.

Completion contract:

```json
{
  "terminal_state": "completed",
  "reasoning_events_min": 1,
  "reasoning_complete": true,
  "allowed_final_statuses": ["passed", "completed"],
  "forbid_blockers": true
}
```

For a native backend also require `backend_executed: true`, `backend_verified: true`, `exit_code: 0`, and the expected backend/version fields. A workflow without a native backend MUST NOT fabricate those fields.

## Runtime adapter invariant

The execute hook for a reasoning-required workflow MUST always execute the PRISM entrypoint and install the host `on_reasoning` callback. If an artifact is supplied, pass it into PRISM as input or execute it only after reasoning completes. Do not branch directly to native execution before `execute_prism`.

The verify hook MUST reject:

- zero reasoning events;
- missing or incomplete declared reasoning steps;
- a blocked/rejected/failed final disposition;
- non-empty final blockers when forbidden;
- missing native evidence when the workflow claims native verification;
- a digest mismatch between executed and reported artifacts.
- missing, duplicated, reordered, or skill-mismatched native agent receipts;
- a required source binding without a content-addressed consumed-source receipt.

Custom execute hooks MUST explicitly project `agent-invoked` entries from the native
PRISM trace into worker events. Returning or retaining a trace object inside package
state is insufficient: Lunar can display only persisted run events. Projected details
MUST include `event_kind`, `agent_name`, `workflow_occurrence`,
`activated_skill_ids`, and native effect linkage when the agent performs an effect.

## Deterministic conversion

All discovery order, resource order, references, file lists, and generated identifiers MUST be sorted by stable repository-relative keys. Normalize text to UTF-8 NFC with LF endings and one terminal newline. Canonicalize JSON with sorted keys and no NaN. Canonicalize YAML through a safe parser and sorted-key emitter. Preserve binary bytes exactly.

Do not include timestamps, random UUIDs, temporary paths, usernames, absolute source paths, process IDs, unordered set iteration, or environment-dependent values. Content-address generated documents. Fix ZIP member timestamps and permissions through Lunar's archive builder. Generate a conversion lock containing source and packaged digests.

Run two exports in independent temporary directories and require identical archive SHA-256 values.

## UI execution acceptance

For every runtime workflow:

1. Select the imported package version in Lunar.
2. Prepare the runtime successfully.
3. Confirm the project and workflow appear in the Prism selectors.
4. Open the Run dialog and confirm every required field has a plausible value.
5. Run through the material entrypoint with the declared model and capabilities.
6. Confirm reasoning entries appear while the run is active.
7. Confirm the terminal state is `completed`, not merely that the worker returned a value.
8. Open the final report and compare its headings and structured fields with the workflow's completion contract.
9. Run `validate_lunar_run.py` for an independent machine-readable check.

The live validator MUST compare the ordered agent/skill receipts and required source
receipts against `metadata.provenance_contract`. A run with complete reasoning but no
expected agent receipts fails. A run with no source receipts passes only when the
contract requires none.

A report showing a successful backend beside a final `blocked` disposition fails. A completed run with zero reasoning entries fails. A final passed disposition without required backend evidence fails.
