<!--
SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>

SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
Neuro-symbolic AI Group

SPDX-License-Identifier: Apache-2.0
-->
# Post-plan reasoning verification lifecycle

## Placement and purpose

New-workflow, extension, and refinement planning add
`post_plan_reasoning_verification` after the initial plan is established and
before release, test, or health review. The stage emits a
`lunar.planner.post-plan-evidence-verification/v1` sidecar bound to the
exact initial-plan digest. Direct-use planning omits the stage and keeps its
smaller invocation-only boundary.

This layer verifies the *planned means of reasoning*: whether material claims
have grounding obligations, source-authority rules, deterministic or symbolic
checks where possible, bounded generative roles where necessary, explicit
uncertainty, and proportionate failure consequences. It neither executes the
plan nor establishes that prospective evidence is valid.

## Non-interference contract

The verifier receives an immutable initial plan and returns an additive
sidecar. It cannot select another route, reorder stages, change bindings,
retrieve sources, invoke providers, install software, or mutate the plan. Any
repair is a proposal addressed to a stable plan location; the existing
refinement lifecycle decides whether to adopt it. The initial plan digest must
remain unchanged.

Failures are local by default. A missing source locator can block one planned
claim without invalidating an unrelated exploratory analysis. Propagation is
allowed only through an explicit route-critical dependency. User constraints,
prospective actions, declared unknowns, placeholders, and properly labeled
hypotheses are not treated as unsupported factual claims.

## Verification posture

The stage chooses the least-flexible adequate verifier:

- deterministic checks for schemas, identities, units, exact extraction,
  hashes, arithmetic, provenance closure, and typed handoffs;
- symbolic checks for encoded ontology, temporal, scope, premise, and
  claim-ceiling constraints, with `entailed`, `contradicted`, or `unknown`;
- statistical checks for estimands, uncertainty, calibration, sensitivity,
  and stochastic behavior;
- generative checks for genuinely semantic extraction, synthesis, rivals, and
  critique inside an allowed-evidence envelope; and
- human review for value-laden or authority-sensitive decisions.

Exploratory work is assessed for traceability, useful discrimination,
calibrated posture, and a clear follow-up test. It is not required to possess
confirmatory evidence before it may be planned. Conversely, a high semantic
score cannot override failed provenance, authority, exact-value, or
claim-ceiling checks.

## Handoff and release

The sidecar records claim- and node-local dispositions such as `pass`,
`pass_with_caveat`, `revise_plan`, `defer`, `block`, and `inconclusive`, plus
the responsible owner and proposed repair. Downstream test, health, and release
reviews consume those findings explicitly. They must describe a passing result
as `verification_ready`, never `evidence_validated` or `executed`.

The complete representation model, authority heuristics, claim ceilings, and
implementation backlog are documented in
[post-plan evidence and determinism verification](../governance/post-plan-evidence-verification.md).
