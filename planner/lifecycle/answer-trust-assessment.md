<!--
SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>

SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
Neuro-symbolic AI Group

SPDX-License-Identifier: Apache-2.0
-->
# Answer-trust assessment lifecycle

Answer trust is an opt-in planner governance layer for one exact answer. It
measures auditable grounding and hallucination-control posture; it is not a
probability that the answer is true. The layer never treats a plan, model
memory, generated prose, or a citation added after generation as observed
evidence.

## Lifecycle placement

```text
sealed initial plan
  -> post-plan evidence verification
  -> answer-control-readiness (prospective and score-free)
  -> refinement and controlled execution
  -> retrospective provenance reconciliation
  -> artifact/quality assessment
  -> answer-trust-assessment (realized and answer-bound)
  -> existing delivery authorization
```

`answer-control-readiness/v1` is a pure sidecar. It reports planned evidence
routes, generative boundaries, preservation obligations, missing receipts, and
the highest attainable *control band*. It neither changes the sealed plan nor
emits a numeric answer score.

`answer-trust-assessment/v1` is retrospective and answer-bound. It is
constructed only after the exact answer,
material-claim denominator, and retrospective receipts exist. It may narrow or
hold delivery under an enabled policy, but cannot override another must-pass
failure, expand source authority, or authorize execution.

## Required joins

Every realized assessment binds the following identities:

- exact answer digest and stable output-component selectors;
- frozen material-claim inventory and typed exemptions;
- base-plan, evidence-manifest, policy, retrospective-provenance, and quality
  assessment digests;
- observed evidence and computation receipts with source locators;
- every lossy or generative derivation receipt, including protected-field
  checks and independent verifier identity; and
- human decisions where policy requires named authority.

A missing join is visible as a cap, score interval, `insufficient_evidence`, or
`not_calculable`. It is never inferred from temporal adjacency or a prospective
workflow edge.

## Interpreting the result

The machine-readable artifact contains per-claim dimension grades, gates,
caps, score inputs, an aggregate score interval, coverage, diagnostics,
remediations, policy version, and its own digest. The user-facing trust card is
a projection of that artifact. It must use control-posture labels:

- `high_control` (85–100), with every critical claim at least 70;
- `substantiated` (70–84);
- `guarded` (50–69);
- `low` (25–49); and
- `blocked_untrusted` (0–24).

These labels never warrant clinical, legal, regulatory, or scientific truth.
An interval wider than 20 points, incomplete material-claim coverage, or
planned-only provenance suppresses a crisp score.

## Operator trace and reassessment

For every displayed number, start with the trust card's assessment digest,
open the claim ledger, and follow the claim's component ID through its observed
derivation path to exact evidence locators and transformation checks. Gates and
caps identify the failed join and the minimum repair; adding more citations or
more fluent prose without repairing that join cannot improve the score.

Reassess after a change to the answer, material-claim inventory, source or
content version, derivation, provider/model, generative envelope, verifier,
provenance reconciliation, quality assessment, or score policy. Selective
invalidation retains receipts for unrelated claims, but a changed answer
digest always prevents reuse of the old answer-level assessment.

## Rollout and calibration limits

Rollout states are `off`, `fixture`, `shadow`, `audit`, `advisory`, and
policy-selected `enforcement`. Fixture and shadow results have no delivery
authority. Advisory exposes the trust card but does not block. Enforcement is
restricted to published high-impact gates and has a pinned rollback to `off`.
The pure `resolve_answer_trust_rollout()` policy resolver keeps enforcement in
advisory mode until fabricated-value detection, citation-lineage detection,
planned-as-observed escapes, deterministic replay, compatibility, false-block,
latency, artifact-size, and reviewer-capacity thresholds all pass.

The disclosed benchmark corpus exercises behavior and determinism; it is not a
confidential certification set. Score weights and bands require blinded expert
calibration on a separately frozen corpus. Report deterministic escape
detection separately from semantic-review agreement, including false-block
rate, interval coverage, band confusion, and inter-reviewer disagreement.
`calibrate_answer_trust()` computes those metrics from blinded, independently
reviewed rows and refuses release-candidate tuning or under-reviewed cases; it
does not claim that the disclosed synthetic fixture is expert certification.

## User-facing explanation template

Communicate status, interval, control band, grounded claim coverage, evidence
composition, weakest critical claims, applied gates, and concrete repairs.
Describe what was checked without exposing hidden chain-of-thought. For
example: “Guarded: one critical full-text claim lacks an exact verified span;
the remaining five material claims have closed observed lineage. Retrieve and
verify the named table, then reassess under policy v1.”
