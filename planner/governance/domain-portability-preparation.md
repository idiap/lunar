<!--
SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>

SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
Neuro-symbolic AI Group

SPDX-License-Identifier: Apache-2.0
-->
# Conservative preparation for cross-domain planner portability

> **Status: design backlog; not implemented and not implementation authority.**
> This document prepares reversible extension seams. It does not authorize a
> package split, namespace migration, profile rewrite, or change to planner
> behavior. The executable backlog is
> [`domain-portability-todos.json`](domain-portability-todos.json).

## Decision

The planner is already **distribution-portable**: it builds as an isolated
wheel, packages its resources, accepts typed host ports, and can plan from an
in-memory surface. It is not yet fully **domain-portable**: Lunar vocabulary,
provider families, report inheritance, external ecosystems, owner scopes, and
some routing rules remain embedded in the public entrypoint, staged router,
profiles, and schemas.

The lowest-risk preparation is an additive compatibility layer:

1. freeze the existing Lunar behavior as a golden baseline;
2. resolve an immutable planner bundle and context once per request;
3. make the current Lunar policy the unchanged default bundle;
4. move one characterized policy seam at a time behind the bundle;
5. prove isolation with a small fixture-only second domain; and
6. defer physical package separation and neutral renaming until two-domain
   parity demonstrates that they have operational value.

This approach generalizes configuration and policy ownership without creating a
second parser, router, workflow language, executor, or catalog.

## Compatibility invariants

Every preparatory increment must preserve these invariants unless a later major
contract explicitly supersedes one:

- `run_planner_request` remains route-only: no workflow execution, network
  retrieval, installation, goal creation, or unauthorized persistence;
- existing imports, public compatibility-call signatures, receipt authority fields, route modes,
  logical profile IDs, continuation semantics, and persisted plans remain
  readable;
- the omitted-bundle path selects the Lunar default and produces the same
  authoritative decisions as the current implementation;
- direct-use precedence, requirement coverage, typed gaps, two-freeze quality
  control, provenance, content addressing, and post-plan non-mutation remain
  kernel behavior;
- no lower policy layer may relax kernel authority, trust, or side-effect
  constraints;
- unknown providers, owners, contract majors, aliases, or policy conflicts fail
  closed and visibly—never by silent substitution or last-write-wins;
- semantically unordered catalog collections cannot change canonical outcomes
  when permuted; profile stages, precedence lists, and ranking rules remain
  intentionally order-sensitive;
- a neutral domain cannot receive Lunar candidates, vocabulary, sources,
  audiences, report controls, Lunar-specific claim-ceiling policy, or cached
  state; generic evidence-calibration controls remain available; and
- default receipt digests must not change merely because portability metadata
  exists. Bundle metadata is initially opt-in or carried in a separately
  versioned resolution receipt.

## Current coupling map

| Surface | Reusable kernel | Domain or host coupling to isolate | Conservative seam |
|---|---|---|---|
| `portable.py`, `store.py`, `provenance.py`, `control.py`, quality and post-plan verification | Canonicalization, hashes, persistence, state control, evidence and quality governance | Little intrinsic biomedical meaning | Freeze and characterize; do not relocate |
| `staged_routing.py` | Request-to-plan lifecycle, ledgers, adjudication, binding, refinement | Biomedical defaults, report/manuscript recognizers, exact skill-ID adjustments, controlled-report activation | Pass an immutable context; replace rules individually after parity fixtures |
| `entrypoint.py` | Public compatibility shell and orchestration | Capability signals, BioConductor/Biomni activation, resource paths, pharmaceutical routes, report behavior | Keep the shell; delegate through the default bundle one seam at a time |
| `ports.py` | Useful typed host boundaries | Process-global mutable configuration; declared workflow/archetype ports are not fully consumed | Add per-request context; retain globals as a compatibility adapter |
| `archetypes.py` | Normalization and selection mechanics | Lunar surface schema IDs, paths, and biomedical archetype registry | Generic normalized surface plus injected archetype rows |
| `provider_families.py` | Family selection algorithm | Biomedical family/decomposition/quality tables | Declarative Lunar provider-family policy pack |
| `bioconductor.py`, `biomni.py`, `external_sources.py` | Optional provider planning patterns | Concrete biomedical ecosystems and lexical activation | Explicit provider bindings, lazily selected by a bundle |
| `report_inheritance.py` | Controlled-deliverable inheritance pattern | Scientific paper/report blueprint and criteria | Optional artifact-family policy; Lunar keeps current blueprint |
| `contracts.py`, profile schema and YAML | Versioning and lifecycle topology | Fixed scopes, `selected_package_skills_and_workflows`, Lunar runtime owners | Add v2/aliases and policy-declared owners; keep v1 valid |
| standalone verifier and release checks | Real isolated-distribution evidence | Biomedical-only probe, hard-coded resources, wheel-only install | Discover manifests; test wheel and sdist with a neutral host fixture |

## Target model

### Stable kernel

The kernel owns deterministic mechanics and non-negotiable authority: canonical
JSON and digests, dialogue and requirement ledgers, route adjudication,
immutable draft/instantiation, refinement and invalidation, acceptance/TODO
state, provenance, evidence controls, quality authorization/evaluation, schema
validation, and next-step closure. Domain packs can supply inputs to these
mechanics; they cannot replace them.

### Resolved planner bundle

A versioned `PlannerBundle` is data plus named, explicitly injected provider
bindings. It is never an auto-discovered executable plugin. Its resolved form
contains:

- bundle ID, version, digest, and compatible kernel range;
- mode-to-profile logical IDs and admitted owner/capability scopes;
- capability vocabulary, aliases, taxonomy, and ranking-rule references;
- domain-policy and artifact-family policy references;
- archetype, provider-family, external-source, and inheritance registries;
- immutable catalog/resource snapshot declarations; and
- names of host-supplied provider bindings.

Resolution is deterministic, schema-validated, and performed once per request.
Paths are confined to declared packaged/host resources. Declarative packs cannot
contain executable payloads or dynamically import code.

### Per-request planner context

An immutable `PlannerContext(bundle, ports, config, host_policy)` carries the
resolved bundle through planning. Immutability requires a frozen snapshot of
binding identities and configuration, request-local or explicitly thread-safe
providers, and context-digest-keyed caches—not merely a frozen container around
mutable ports. A new explicit-context entrypoint leaves the existing public
signature literally unchanged. Existing `configure()` and `configure_ports()`
remain initially as compatibility wrappers that construct the default context.
The explicit path must never consult those process globals. Removing globals is
a later deprecation decision, not a preparation step.

### Policy precedence

The only valid precedence is:

1. kernel safety and authority invariants;
2. host governance policy;
3. domain policy;
4. resolved profile;
5. request preferences.

A lower layer may monotonically narrow authority or add controls, but cannot
relax an upper layer. Compatible narrowing composes; attempted widening blocks
as an authority violation; incomparable values or same-layer disagreement block
as a policy conflict. Each blocker names both policies, the affected field or
stage, the precedence basis, and a local repair.

Host governance is an explicit, digest-bound policy input rather than an
ambient setting. Symbolic provider-binding IDs resolve only through a
host-constructed allowlisted registry whose binding identities and versions are
recorded. Packs may not use module strings, file paths, Python entry points, or
other dynamic-import mechanisms as bindings.

### Capability evolution

Continue accepting the current descriptors. Add a v2 normalized view only when
the compatibility corpus exists. It may add stable logical ID, provider
namespace, contract major, domain tags, capability roles, typed inputs/outputs,
invocation posture, side effects, availability, quality/policy references,
binding lineage, and content digest. Collisions use
`(provider_namespace, logical_id, contract_major)`. Aliases aid discovery but
never prove semantic equivalence. Unknown information stays unknown.

### Profiles and schemas

Do not rename `lunar.planner.*` contracts. They are compatibility protocol
identifiers, not a barrier to neutral behavior. Introduce additive contract
versions and stable schema aliases when needed. Profile overlays must be
resolved deterministically before execution. Arbitrary DAG overlays are deferred:
blocking additions require a predeclared extension-aggregation node already on
the release path, while post-release additions are advisory only. Until that
contract is proven, foreign bundles use fully resolved profiles. No overlay may
delete dependencies, replace stages, relax authority, shadow outputs, introduce
undeclared root inputs, bypass gates, or create ambiguous owners.

## Migration method

Each policy extraction follows the same reversible loop:

1. characterize the exact current rule with canonical byte/JSON fixtures plus a
   versioned semantic projection whose only normalization is an enumerated
   timestamp/nonce allowlist;
2. add an opt-in bundle lookup that dual-reads the existing value;
3. run legacy and bundle paths in shadow mode;
4. require exact equality on authoritative fields and an explicit allowlist for
   additive diagnostics;
5. keep every extraction non-authoritative and shadow-only until the complete
   bundle path passes the promotion matrix;
6. retain the legacy reader and legacy-v1 writer through the support window;
   and
7. use a request/context-scoped selection plus a pinned known-good release for
   rollback; an emergency process default cannot mutate an existing context.

The extraction order is deliberately narrow: profile mapping and vocabulary,
resource snapshots, admitted scopes, provider-family tables, external provider
activation, report inheritance, then specialized domain routes. The large
entrypoint and staged state machine are never rewritten in one operation.

## Second-domain proof

Use a fixture-only `software-assurance-demo`, not a new production commitment.
Its catalog can include `sbom-reader`, `vulnerability-correlator`,
`remediation-prioritizer`, `assurance-report-writer`, and `release-critic`.

Example request:

> Build a workflow that inventories dependencies, correlates pinned
> vulnerability evidence, prioritizes remediation, and emits an auditable
> assurance report.

The proof passes only if it uses the same planner lifecycle and deterministic
controls, requires no kernel edit, resolves only demo descriptors and policies,
preserves provenance and typed gaps, and emits no biomedical vocabulary,
provider, audience, inheritance blueprint, or Lunar-specific claim-ceiling
policy. Generic claim calibration remains active. Tests must include a
non-report journey, empty/minimal catalogs, renamed logical IDs, missing-policy
cases, and lexical-collision negatives such as `cell`, `culture`, `pipeline`,
`clinical`, and `release`. They must also run Lunar → demo → Lunar
sequentially, re-entrantly, and concurrently in one process, including provider
failure, cancellation, teardown, and import-order permutations.

## Promotion gates

| Gate | Required result |
|---|---|
| Legacy semantics | Exact match on mode, status, authority, ordered selected candidates, requirement coverage, blockers, and continuation validity |
| Safety | Zero execution, network, installation, goal creation, or unauthorized persistence |
| Domain isolation | Complete required-capability coverage with zero cross-domain policy or cache leakage |
| Mutation robustness | Unordered-collection permutations preserve canonical results; ordered policy/profile mutations are detected; malformed contracts fail closed |
| Contract compatibility | Old/new readers and writers pass within declared ranges; unsupported majors block visibly |
| Host compatibility | Direct package and compatibility facade produce equivalent authoritative results |
| Distribution | Wheel and sdist install in separate isolated environments and run with declared packaged or explicitly host-deferred resources only |
| Configuration isolation | Two contexts plan sequentially and concurrently without contamination |
| Performance | No material regression in deterministic planning latency or artifact size |

Any safety regression, stored-plan unreadability, continuation failure, legacy
authoritative-field mismatch, or cross-domain leakage triggers immediate
rollback. Ranking experiments may use a separately documented tolerance only
after authority and compatibility fields pass with zero tolerance.

## Explicit non-goals and dangerous shortcuts

- no package, module, schema-ID, receipt-key, profile, or artifact-root rename;
- no neutral core/domain wheel split during preparation;
- no automatic Python entry-point/plugin discovery;
- no second router, parser, surface-index builder, DSL, or executor;
- no runtime rewriting of persisted namespaces or stored plans;
- no implicit, order-dependent YAML fragment merging;
- no assumption that aliases are semantically interchangeable;
- no bulk relocation of embedded rules before characterization; and
- no claim that package isolation alone proves domain portability.

## Recommended first implementation increment

Only `PDG-001` through `PDG-009` should be considered together initially. They
freeze behavior, establish the threat model and compatibility policy, define
but do not activate bundle/context contracts, and create the unchanged
`bioagents-default` bundle. Host-only resources remain typed as deferred until a
Lunar host catalog supplies them. This produces a useful seam while leaving
routing decisions, public contracts, persisted artifacts, and default digests
intact.
