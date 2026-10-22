---
name: repository-prism-package-converter
description: Convert all workflows, executable skills, and declared data sources in a repository into one deterministic Lunar-importable PRISM package, then prove that every exported workflow is structurally valid, runtime-bound, reasoning-complete, and runnable from the Lunar UI. Use for repository-to-PRISM migrations and package corrections; do not use for exporting a single isolated workflow or for static documentation-only snapshots.
---
<!--
SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>

SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
Neuro-symbolic AI Group

SPDX-License-Identifier: Apache-2.0
-->

# Repository PRISM Package Converter

Produce exactly one package per source repository. Preserve the complete behavior of every in-scope workflow: reasoning stages, loops, branches, backend calls, reviews, repair paths, artifacts, provenance, and terminal-report semantics. A structural sketch, placeholder binding, fake handler, unexecuted native shortcut, or report-only emulation is not a conversion.

## Required procedure

1. Inventory the repository before writing PRISM. Find workflow definitions, their executable implementations, skill dependencies, data sources, runtime/backend adapters, input examples, output/report contracts, and validation commands. Record explicit exclusions; never silently omit an unsupported workflow.
2. If inventory finds any workflow with an associated source output report, you MUST load
   the sibling `repository-prism-report-compatibility` skill and follow it for every such
   workflow. Create its report-association manifest before implementing report output. If
   there are no associated reports, record that finding explicitly; do not invoke the
   companion on unrelated workflows.
3. Read [references/conversion-contract.md](references/conversion-contract.md) before designing the converted graph. Use [references/export-config.md](references/export-config.md) when authoring the package configuration.
4. Create a repository-owned conversion tree, normally `<repo>-prism/`, containing one project directory per workflow plus a catalog, source fingerprints, a deterministic generation record, and runtime adapters. Keep the original workflow identity traceable. Do not copy this skill into the repository.
5. Convert semantics, not filenames. Every material operation must call its real packaged implementation or an explicitly declared host capability. Every reasoning occurrence must execute through PRISM and emit started/completed events. Native backend execution may follow reasoning, but must not bypass it when a non-empty artifact input is supplied.
6. Convert all in-scope skills and data sources deterministically. Use stable IDs, sorted paths, canonical JSON/YAML, normalized UTF-8 text, exact binary bytes, content digests, and no timestamps or machine-specific absolute paths. References must resolve inside the package or be declared remote references.
7. Define a `# lunar-runtime:` registration for every runnable workflow. Required UI inputs need meaningful deterministic defaults or examples; fixture tokens and placeholders are forbidden. Bind the material entrypoint, prepare/execute/verify hooks, model requirements, capabilities, timeout, reasoning contract, and completion contract explicitly. Also declare `metadata.provenance_contract` with the exact ordered native agent invocations, their workflow occurrences and activated skill IDs, plus every required source read. Package-level skill and data-source declarations are dependencies, not evidence that a run used them.
8. Author one `prism-export.json` at the repository root. Run `scripts/export_repository_prism.py` with `--verify-reproducible`; two independent builds must be byte-identical.
9. Run `scripts/validate_prism_package.py` on the archive. Fix every error. Do not weaken validators or convert an error into a warning.
10. Import the archive through the Lunar UI, prepare its runtime, and run every workflow at least once using its representative default/example input. A workflow is not UI-runnable merely because its package imports.
11. After each run, use `scripts/validate_lunar_run.py` and inspect the rendered UI report. Completion requires a terminal completed run, a non-empty complete reasoning log, a final non-blocked disposition, and any declared backend evidence. Preserve failed attempts as evidence, but determine the final disposition from the authoritative successful receipt. The run must also match its provenance contract exactly: custom execute hooks must project native `agent-invoked` trace entries with their actual activated skills, and every required source binding must have a content-addressed consumed-source receipt.
12. For each workflow associated with a repository report, run the companion report
    compatibility validator on the exact source bytes and final `typed-report.json`,
    complete its independent semantic assessment, and inspect the rendered Report UI.
    The conversion is incomplete until every associated report passes both deterministic
    and semantic gates.

## Non-negotiable completion rules

- Package import success is necessary but insufficient.
- All declared reasoning occurrences must have ordered `running` then `completed` transitions.
- A workflow requiring reasoning must call `execute_prism(...)` with an `on_reasoning` callback. An `execute_artifact(...)` shortcut must never replace that call.
- Host success must be fail-closed on the reasoning and completion contracts, not merely on a returned `status` string.
- Backend claims require native receipts. Model text, static review, or artifact presence cannot set `backend_executed` or `backend_verified`.
- Workflow `skill_ids` do not prove skill activation. Every expected agent invocation must be visible in the run API with the exact activated skills recorded by PRISM.
- Data-source availability does not prove consumption. Require a source receipt only for an explicit required workflow binding, and never fabricate reads merely to populate UI.
- The final report must reconcile pre-execution review with execution evidence. A provisional pre-execution `blocked` result may remain visible, but the authoritative final disposition must become `passed` only after all required evidence succeeds.
- A workflow with an associated repository report MUST terminate in
  `prism.reporting.report.Report`, preserve the source report semantically, and pass
  `repository-prism-report-compatibility`. Native Markdown/JSON/HTML alone is insufficient.
- Do not claim completion while any exported workflow remains unrun, blocked, structurally simulated, or dependent on undeclared local state.

## Commands

Resolve this installed skill's directory from the active Codex skills catalog and use its absolute path as `SKILL_DIR`. Do not assume the target repository contains the skill.

```bash
python3 "$SKILL_DIR/scripts/export_repository_prism.py" \
  --root . --config prism-export.json --lunar-root ../lunar-platform \
  --output artifacts/prism/<repository>.zip --verify-reproducible

python3 "$SKILL_DIR/scripts/validate_prism_package.py" \
  artifacts/prism/<repository>.zip --lunar-root ../lunar-platform

python3 "$SKILL_DIR/scripts/validate_lunar_run.py" \
  --base-url http://localhost:8080 --package-version-id <uuid> \
  --workflow-id <runtime-workflow-id> --run-id <uuid> --cookie-file <cookie-file>
```

When report associations exist, resolve the companion skill directory as
`REPORT_SKILL_DIR` and also run:

```bash
python3 "$REPORT_SKILL_DIR/scripts/validate_report_compatibility.py" \
  --root . --manifest <conversion-tree>/report-compatibility.json --json
```

The live validator verifies the same API state rendered by the UI; still open the run and final report in the browser to catch presentation or navigation defects.
