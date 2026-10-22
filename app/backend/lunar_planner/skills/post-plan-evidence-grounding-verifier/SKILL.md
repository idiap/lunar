---
name: post-plan-evidence-grounding-verifier
description: Classify the evidence, representation, inference, and verification obligations of an already-instantiated Lunar plan and emit a digest-bound sidecar without rewriting the plan. Use after persistent new, extended, or refined workflow planning; do not use for control routes, exact direct use, workflow execution, or post-run evidence validation.
---
<!--
SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>

SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
Neuro-symbolic AI Group

SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
Neuro-symbolic AI Group

SPDX-License-Identifier: Apache-2.0
-->

# Post-Plan Evidence Grounding Verifier

This skill owns the semantic classification of a post-plan verification sidecar.
The deterministic kernel lives in `lunar_planner.post_plan_verification`; do
not replace exact runtime checks with prose judgment.

## Workflow

1. Accept only an immutable workflow instantiation and its verified digest.
2. Type material planned assertions as extracted facts, deterministic or symbolic
   derivations, statistical results, bounded synthesis, exploratory hypotheses,
   user constraints, future actions, execution states, or unknowns.
3. Assign the least-flexible adequate verification method: deterministic,
   symbolic, statistical/computational, bounded generative, or human.
4. Compile claim-relative source authority, directness, currency, applicability,
   conflict-search, and claim-ceiling obligations. Model memory is not evidence.
5. Preserve useful exploratory hypotheses when their posture, evidence basis,
   uncertainty, rivals, discriminating test, and prohibited promotions are clear.
6. Return local findings, verification test specifications, and proposed repair
   TODOs. The existing refinement lifecycle decides whether to apply repairs.

## Output boundary

Emit `lunar.planner.post-plan-evidence-verification/v1`, bound to the exact
`workflow_instantiation.digest`, with `route_only: true` and
`execution_authorized: false`. Distinguish `verification_ready` from actual
post-execution `evidence_validated` status.

Block only material defects such as fabricated or non-resolving sources, missing
provenance represented as fact, exact value/unit mismatch, generator self-review,
claim promotion beyond evidence, observed execution inferred from a planned route,
or mutation of the base plan. Use advisories for optional determinization,
triangulation, or stronger sources. Localize unknowns and never silently
substitute an unavailable source.
