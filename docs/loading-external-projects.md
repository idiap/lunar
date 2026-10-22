<!--
SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>

SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
Neuro-symbolic AI Group

SPDX-License-Identifier: Apache-2.0
-->
# Loading external projects

Lunar loads an external project as one versioned PRISM package ZIP. It does not
load a Git URL, source checkout, or arbitrary directory directly. Convert the
source repository, validate the resulting archive, import it, prepare its
isolated runtime, and execute every exported workflow before treating the
project as loaded.

The repository vendors the
[`repository-prism-package-converter`](../.codex/skills/repository-prism-package-converter/SKILL.md)
skill used by this procedure. The skill is normative when it is stricter than
this overview.

## 1. Inventory the source repository

Work from the external repository root. Identify every workflow definition and
implementation, executable skill, declared data source, backend/runtime adapter,
representative input, output contract, source report, and existing validation
command. Classify every discovered workflow as `converted`, `excluded`, or
`blocked`, recording a reason for the latter two. One source repository must
produce one package, even when it contains several workflows.

If any workflow owns or produces a repository report, also use the sibling
`repository-prism-report-compatibility` skill. Create its report-association
manifest before implementing report output. Such a workflow must terminate in
a real `prism.reporting.report.Report`; Markdown, JSON, or HTML alone is not an
equivalent terminal value.

Before implementing the conversion, read the vendored
[conversion contract](../.codex/skills/repository-prism-package-converter/references/conversion-contract.md)
and [export configuration contract](../.codex/skills/repository-prism-package-converter/references/export-config.md).

## 2. Build a complete conversion tree

Create a repository-owned tree such as `<repository>-prism/`, with one project
directory per workflow, a catalog, source fingerprints, deterministic generation
records, and runtime adapters. Add one `prism-export.json` at the external
repository root.

For each runnable workflow:

- preserve its branches, loops, retries, reasoning stages, native calls, review
  and repair paths, artifacts, provenance, and terminal semantics;
- bind material operations to their real packaged implementation or an explicit
  host capability;
- add one `# lunar-runtime:` registration to its material entrypoint, including
  input/output schemas, prepare/execute/verify hooks, model and capability needs,
  timeout, reasoning contract, completion contract, and provenance contract;
- give every required UI input a meaningful deterministic default or example;
- declare exact ordered agent/skill activations and only the source reads the
  workflow actually requires; and
- call `execute_prism(...)` with an `on_reasoning` callback whenever reasoning is
  required. A native or artifact shortcut must not bypass that reasoning path.

Keep package content deterministic: use stable IDs, sorted repository-relative
paths, canonical JSON/YAML, normalized UTF-8 text, exact binary bytes, and content
digests. Do not embed timestamps, random identifiers, usernames, temporary paths,
or machine-specific absolute paths in the package.

## 3. Export and validate the archive

Set `LUNAR_ROOT` to this Lunar checkout and run the vendored tools from the
external repository root. Replace `my-project` with the package archive name.

```sh
LUNAR_ROOT=/absolute/path/to/lunar-platform
SKILL_DIR="$LUNAR_ROOT/.codex/skills/repository-prism-package-converter"

python3 "$SKILL_DIR/scripts/export_repository_prism.py" \
  --root . --config prism-export.json --lunar-root "$LUNAR_ROOT" \
  --output artifacts/prism/my-project.zip --verify-reproducible

python3 "$SKILL_DIR/scripts/validate_prism_package.py" \
  artifacts/prism/my-project.zip --lunar-root "$LUNAR_ROOT"
```

`--verify-reproducible` performs two independent exports and requires the ZIP
bytes to match. Fix every package validation error; do not weaken the validator.
If reports are associated, also run the report-compatibility validator against
the exact source bytes and final `typed-report.json`, then complete its independent
semantic assessment.

## 4. Import and prepare in Lunar

Start Lunar using the [installation and operator guide](../app/README.md), sign
in, then:

1. Open **Repository**, choose **Import package**, and select the generated ZIP.
2. Confirm the imported version is selected in **Package version**. A successful
   import is `ready` but its runtime is still `unprepared`.
3. Choose **Prepare runtime** and wait for `Runtime: ready`. Preparation installs
   locked dependencies into a version-specific worker image; upload itself never
   installs or executes package code.
4. Browse **Skills**, **Data Sources**, and **Repository** to confirm the declared
   resources are present. Open **Prism** and confirm every converted project and
   workflow is selectable.

Import failures leave prior versions and the current selection intact. Uploading
the same bytes again creates a new version and requires its own preparation.
See [package import behavior](package-imports.md) for API, storage, ownership,
limits, and recovery details.

## 5. Run and accept every workflow

In **Prism**, run every workflow once with its representative schema default or
example. For each run, confirm that reasoning entries appear, the terminal state
is `completed`, the final disposition is non-blocked, and declared backend and
source evidence is present. Open the final report and inspect its content and
navigation; imported successfully does not mean executable successfully.

Then validate the same persisted run state through the API:

```sh
python3 "$SKILL_DIR/scripts/validate_lunar_run.py" \
  --base-url http://localhost:8080 \
  --package-version-id 11111111-1111-1111-1111-111111111111 \
  --workflow-id my-project-workflow-execute \
  --run-id 22222222-2222-2222-2222-222222222222 \
  --cookie-file /secure/path/to/lunar-cookie.txt
```

Use the real IDs returned by Lunar; the values above only show their required
shape. Run this validator separately for every workflow. A project is fully
loaded only when all exported workflows pass both live validation and rendered
UI inspection, provenance receipts exactly match their contracts, and every
associated report passes deterministic and semantic compatibility checks.
