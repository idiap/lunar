<!--
SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>

SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
Neuro-symbolic AI Group

SPDX-License-Identifier: Apache-2.0
-->
# Unified skill and workflow visibility

## Goal

Every future skill and workflow must become visible through the same generated
discovery surface in the iteration immediately after it is proposed or
admitted. Equal visibility does not imply equal executability: proposed design
records are searchable but cannot be dispatched, while admitted canonical
records are invocable only after contract, registration, route, and test gates
pass.

The adapted surface index reuses effective descriptors for every scientific
and project-support skill and discovers every canonical top-level workflow
package plus every promoted universal subworkflow. It is a derived navigation
view and never becomes a second source of truth.

## One discovery model

The catalog-contract index emits one `invocable_surfaces` collection and typed
views for `skills`, `workflows`, `coordination_stacks`, and `router_helpers`.
All entries share these required fields:

- stable `surface_id`, canonical name, kind, aliases, path, source scope, and
  content digest;
- lifecycle status, visibility state, invocability, direct-use eligibility,
  and the evidence for each decision;
- description, task families, triggers, non-triggers, and negative route
  fixtures;
- typed inputs, outputs, representation contracts, dependencies, validators,
  side effects, authority needs, and claim effects;
- invocation adapter or an explicit reason that no adapter is available;
- owners, component skills or stages, hooks, tests, documentation surfaces,
  provenance, and deprecation or replacement metadata.

Kind-specific fields remain in typed extensions. A skill retains its atomic
reasoning contract and `SKILL.md` anchors. A workflow retains ordered stages,
artifact edges, release gates, runtime environment, terminal artifacts, and
CLI/Python bindings. Equal indexing never flattens these semantic differences.

## Source scopes and lifecycle states

| Scope | Status | Visible | Executable | Meaning |
| --- | --- | --- | --- | --- |
| `design_overlay` | `pre_authoring` | yes | no | Context seed awaiting sufficiency review and Codex skill-creator handoff |
| `canonical_catalog` | `admitted` | yes | no | Canonical body exists but one or more promotion gates remain open |
| `canonical_catalog` | `active` | yes | when explicitly eligible | Validated catalog capability available to routing and composition |
| `canonical_catalog` | `deprecated` | yes | no by default | Tombstoned capability retained for history, aliases, and migration |
| `environment_overlay` | `candidate` | yes in scoped search | no by default | Installed external/user capability that may nominate reuse |
| any | `blocked` | yes with diagnostics | no | Conflicting identity, stale contract, failed validation, or unsafe binding |

The planner directory will be indexed as a `design_overlay`. Its candidate skill
context seeds and proposed workflow profiles are available to future planning
and help with clear `pre_authoring` or `proposed` labels, but they cannot be
selected by direct-use execution or used as canonical composition evidence. A
skill moves beyond pre-authoring only when Codex `skill-creator` returns a
canonical body that passes repository promotion; the overlay itself never gains
canonical authority.

## Canonical manifests

Skills continue to use their effective descriptor derived from canonical
`SKILL.md`, metadata, and reviewed overrides. Runnable and reusable workflows use a required,
versioned manifest under their canonical workflow directory. The manifest
declares:

- workflow ID, name, kind, status, aliases, description, triggers, and
  non-triggers;
- entrypoint bindings and argument schema, or `invocable: false`;
- ordered stage graph with skill/implementation owners and typed artifacts;
- source, representation, dependency, authority, side-effect, hook, validation,
  fixture, release, and deprecation contracts.

The manifest references executable code and tests; it does not duplicate them.
The workflow scanner replaces the hard-coded public-workflow list. Missing or
invalid manifests produce visible blocked rows rather than silently omitting a
workflow.

## Atomic promotion transaction

Promotion of either a skill or workflow is one fail-closed transaction. Skill
bodies entering the transaction must have a matching accepted creator context
packet and Codex `skill-creator` result; the promotion service never authors or
repairs them.

The transaction then:

1. Validate stable identity, canonical location, aliases, lifecycle status,
   typed contracts, ownership, and monotonicity or migration evidence.
2. Validate kind-specific contracts: atomicity and output ownership for skills;
   DAG, stage owners, artifact producers, release gates, and entrypoint binding
   for workflows.
3. Rebuild the unified catalog-contract index and derive the invocable help,
   skill registry, skill catalog, capability map, workflow views, natural-
   language packets, composition graph, generated agent context, and docs from
   the same content snapshot.
4. Run exact-name, alias, positive-trigger, negative-trigger, ambiguity, and
   direct-use binding tests. Proposed or blocked entries must be rejected by
   dispatch even when they are discoverable.
5. Compare the before/after visibility delta and verify that every added,
   changed, deprecated, or removed surface appears consistently in all
   applicable derived views.
6. Publish the content-addressed index and non-hashed build manifest atomically.
   Partial generation or digest disagreement blocks promotion and closure.

No manual edit to one generated surface constitutes publication. Skills and
workflows use the same transaction, coverage report, freshness gate, and
closure evidence.

## Iteration semantics

Each planner version pins a `catalog_snapshot_digest`; it never sees catalog
changes silently during execution. When an implementation iteration admits or
changes a surface, catalog refresh emits:

- `invocable-surface-snapshot.json` for the new complete view;
- `invocable-surface-delta.json` with added, changed, deprecated, blocked, and
  removed records, plus affected routes and consumers;
- `visibility-parity-report.json` proving derived-surface and digest parity;
- `promotion-report.json` recording each gate and final lifecycle state.

The next planning iteration consumes the refreshed digest. Refreshing an active
plan creates a new plan version and invalidates candidate discovery, reuse,
sufficiency, routing, composition, hooks, TODOs, criteria, and tests that depend
on the old snapshot. Unrelated evidence remains reusable when its dependency
digests are unchanged.

Deprecation preserves a tombstone, aliases, replacement route, last valid
contract digest, consumer list, and migration period. Deletion is allowed only
after consumer and alias checks demonstrate that no supported route depends on
the surface.

## Parity and completeness gates

Release requires all of the following:

- 100% of canonical skill bodies and canonical workflow manifests have exactly
  one unified surface row;
- every pre-authoring planner skill context and proposed workflow has exactly
  one visible, non-executable design-overlay row;
- every active invocable surface has one validated adapter, input/output
  contract, owner, test set, and positive and negative routing fixtures;
- every derived view cites the same source snapshot and agrees on identity,
  status, aliases, and invocability;
- no duplicate identity, dangling alias, hidden canonical surface, orphaned
  stage, unproduced artifact, or hard-coded workflow-only exception remains;
- help can filter by kind and lifecycle status and distinguishes “available to
  execute” from “planned for future admission”; and
- catalog refresh is mandatory before planner closure whenever a skill,
  workflow, manifest, route, hook, contract, or generated surface changes.

Coverage is reported separately by kind and status so a high skill count cannot
hide missing workflows, and vice versa.
