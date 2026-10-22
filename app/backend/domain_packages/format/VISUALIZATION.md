<!--
SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>

SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
Neuro-symbolic AI Group

SPDX-License-Identifier: Apache-2.0
-->
# Source-derived PRISM visualization

Packages contain linked `.prism` files, not authored workflow graphs or a
`runtime.workflows` section. Repository `metadata.bundle` and
`metadata.workflows` are rejected. The viewer bundle is an API response generated
by Lunar, never an archive resource required from exporters.

Lunar parses every linked PRISM source with the pinned PRISM language parser.
Every `reasoning` declaration produces a selectable workflow view, including
multiple blocks in one file and blocks in supporting modules. Executable
`workflow` declarations never appear in the workflow selector. IDs derive
from repository identity, source path, and declaration name. Input/output types,
occurrence aliases, locally resolvable callable signatures (including packaged
imports), relations, source spans, sequence/parallel/choice/repeat topology,
argument dependencies, guarded exits, and returns come from syntax. The full
composition tree accompanies the graph. Unresolved external signatures remain
unspecified; the viewer does not fabricate their types. Parsing does not execute
package code, run sample workflows, or fetch imports.

The browser positions the generated nodes deterministically and preserves every
edge endpoint. It does not add convergence, evaluation, or loop nodes based on
names, commentary, or heuristics. Parallel split/join markers and repeat edges
represent actual authored composition blocks.

## Required execution binding

Every PRISM `reasoning` declaration must be paired with an executable `workflow`.
Add a single-line JSON annotation to the materialized workflow source:

```prism
# lunar-runtime: {"declaration":"materialize","prepare_hook":"prepare","input_schema":{"type":"object"}}
```

The annotation binds an existing materialized declaration to the worker protocol;
it cannot register a missing workflow, make `reasoning` executable, or override
its source file/repository/name. `prepare_hook` must identify a
`runtime.entrypoints` preparation hook. The established source-file `main`
entrypoint and preparation protocol still govern execution. When a repository
resource contains exactly one reasoning block, its view is associated with the
execution registration even when the declarations are in different files.
Multiple reasoning blocks require an explicit `metadata.viewer_workflow_id`.
Every view must resolve to at least one registration. If the source set contains
`material_main.prism`, that file must own the registered entrypoint; a reasoning
adapter may never replace it at run time.

Lunar derives a reasoning contract from the associated source graph. A worker's
successful result does not complete the run unless the durable reasoning log has
exactly one `running` then `completed` transition for every declared occurrence.
Missing, incomplete, duplicated, or wrongly attributed occurrences fail the run
before outputs and artifacts are committed. Generic workflows without a bound
reasoning view are unaffected.

Optional fields are `id` (stable public identity), `entry_argument` (defaults to
the first parameter), `input_schema`, `output_schema`, `verify_hook`,
`execute_hook`, and `metadata`. Schemas default to `{}`, verification to `null`,
and metadata to `{}`. Existing schema,
hook, capability, and native verification constraints remain enforced. There is
no graph/topology field. Each declaration permits at most one annotation.

## Existing versions

Existing imported versions remain readable and runnable. Their diagram endpoint
ignores stored viewer assets and regenerates from source. Re-export removes
legacy viewer assets and `runtime.workflows`, and moves execution settings into
source annotations in the private export snapshot. Migration requires exactly
one executable declaration in each legacy entry file; ambiguous entries fail
explicitly. Original stored versions and historical provenance are unchanged.
New imports must satisfy the source-only, runnable contract. Use
`scripts/validate_imported_prism_packages.py PACKAGE_ROOT` to audit exported or
stored versions without executing package code.
