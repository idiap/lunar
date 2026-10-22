<!--
SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>

SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
Neuro-symbolic AI Group

SPDX-License-Identifier: Apache-2.0
-->
# External computational framework reuse

## Goal and identity

The planner must search reusable computational frameworks before proposing new
implementation. The first governed adapters target:

- **Bioconductor** packages, exported functions, classes/methods, datasets,
  vignettes, how-tos, and the official `bioconductor/ai-agent-skills` catalog;
- **Biomni** (`snap-stanford/Biomni`) tools, declarative tool descriptions,
  libraries, databases, know-how, environment manifests, and tests.

The user-facing alias `BioMine` is recorded, but it must be resolved to a pinned
canonical source before use. The adapter must not silently confuse Biomni with
the unrelated historical BioMine graph service or with third-party skill
collections.

## Authoritative discovery surfaces

Bioconductor ingestion uses the official package list and repository metadata,
`BiocManager::available()`, package `DESCRIPTION`, `NAMESPACE`, Rd aliases,
manuals, vignettes, `biocViews`, and the canonical
[`ai-agent-skills` index](https://bioconductor.github.io/ai-agent-skills/SKILLS.html).
Release, R version, package version, repository kind, and source digest are
mandatory identity fields. Installation uses `BiocManager`; a mixed-release
library is invalid.

Biomni ingestion pins the official
[`snap-stanford/Biomni`](https://github.com/snap-stanford/Biomni) commit or
release. It extracts callable definitions from `biomni/tool/`, declarative
contracts from `biomni/tool/tool_description/`, tool registration, libraries
and datasets from `env_desc`, dependency/environment manifests, install scripts,
license metadata, conflicts, and tests. Descriptions nominate functions; the
implementation body and dependency manifests authorize execution.

## External capability index

The implemented Bioconductor package index is selector-owned at
`catalog/agents/readers/tools-and-portals/orchestration-governance-and-control/bioconductor-package-selector/references/index/<release>/`.
The planner surface embeds only a compact descriptor containing release,
counts, facets, digest, and portable relative path. It lazily compiles a
`package_need`, searches that local index, and emits an observable receipt.
Package records are not copied into the main surface index and cannot establish
function-level compatibility.

Any future callable-granularity overlay belongs under
`artifacts/workflows/planner/external-framework-capability-index.json`, with one row per
versioned callable or skill:

- framework ID/aliases, upstream URL, release/commit, retrieval time, digest;
- package/module/skill identity and fully qualified callable;
- kind: exported function, generic/method, class, dataset, vignette, skill,
  Biomni tool, database query, library, or workflow;
- description, task families, inputs, outputs, side effects, determinism,
  resource profile, and evidence anchors;
- representation/schema, identifiers, organism/build, units, granularity,
  null/no-hit semantics, and provenance behavior;
- direct and optional dependencies, system requirements, external services,
  data assets, credentials, licenses, and commercial-use constraints;
- install route, smoke test, known conflicts, deprecation, and maturity flags.

Unknown contracts remain unknown. Dynamic import, execution, or installation is
not allowed during indexing. Generated documentation and declarative metadata
are corroborating sources; package/tool bodies remain authoritative.

## Local-to-external reuse map

`artifacts/workflows/planner/external-framework-reuse-map.json` would join local catalog needs and
skills to pinned external capabilities. Each edge records:

- local workflow stage, skill, or missing capability;
- external callable/skill and exact version;
- relation: `direct_reuse`, `adapter_reuse`, `composed_reuse`,
  `partial_reuse`, `candidate_only`, `incompatible`, or `superseded`;
- semantic-fit evidence, typed input/output compatibility, necessary adapter,
  dependency/environment cost, license/privacy constraints, validation status,
  and fallback.

Search and embeddings may nominate candidates. A reuse decision requires actual
contract/body review and compatibility evidence. Prefer, in order: existing
local skill, local skill backed by an external callable, composition of existing
callables, thin adapter, monotonic local extension, then a Codex skill-creator
handoff for a justified new skill, or custom non-skill implementation.

## Dependency and installation lifecycle

The selected composition produces an `external_framework_environment_spec`.
Deterministic resolvers expand the complete closure across R/Bioconductor,
CRAN, Python, system/CLI, GPU, services, models, and data assets before any
mutation. The spec records pins, repositories, hashes, lockfiles, platform,
resource estimates, licenses, network/credential needs, conflicts, fallbacks,
smoke tests, and teardown/cache policy.

Installation rules:

1. Dry-run resolution and policy review precede installation.
2. Network access, licenses, data volume, credentials, GPU use, and system
   package changes require explicit authority.
3. Install into a new content-addressed environment; never mutate the project
   environment, user library, shell startup files, or another workflow's venv.
4. Use a release-compatible isolated R library and `BiocManager`; run
   `BiocManager::valid()` after installation.
5. Use a locked Python/Conda/Pixi/uv environment for Biomni and install only the
   selected tool slice when possible. Do not trigger the full Biomni data lake
   by default.
6. Verify hashes/signatures when available, capture an SBOM and install log,
   run import/version/function smoke tests, and compare resolved versus actual
   dependencies.
7. Execute Biomni only in a sandbox because its upstream agent can access the
   filesystem, network, and system commands. Secrets remain external handles.
8. A failed or invalid installation emits a blocked environment result and
   cannot fall through to unpinned global packages.

## Planner integration

All three change-planning profiles perform external-framework index validation
and a semantic reuse audit after local sufficiency. The direct-use profile
validates only the dependencies required by its selected existing target. Each
selected composition receives an environment specification before its
executable DAG is frozen. Existing
skills own general reuse, source policy, adapters, contract validation, tests,
and monotonicity. The two remaining atomic reasoning candidates are context
seeds only; if they survive sufficiency review, the planner passes them to
Codex `skill-creator` and validates the returned skills.

For Bioconductor, `bioconductor-package-selector` is the stable conversational
route. Explicit and implicit expert requests compile into traceable facets;
explicit negation is honored. Search failures are `invalid_index` rather than a
silent hand-written-shortlist fallback. The package-search receipt exposes the
normalized need, index digest, filtering/ranking evidence, unknowns,
exclusions, local-wrapper reuse, and verification status. Existing governed
wrappers such as SingleR and crisprDesign routes take precedence over a new
wrapper proposal.
