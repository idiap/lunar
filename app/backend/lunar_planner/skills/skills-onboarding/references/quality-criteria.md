<!--
SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>

SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
Neuro-symbolic AI Group

SPDX-License-Identifier: Apache-2.0
-->
# Skills onboarding quality criteria

A skill is onboarded only when every applicable required gate passes with
observable evidence.

## Required for every skill

- **Identity:** directory name, `SKILL.md` name, `skill.yaml` `skill_id`, and
  `$skill-id` in the default prompt agree; the scoped identity is unique.
- **Discovery:** the description states the capability, trigger, and a useful
  boundary precisely enough to avoid generic routing.
- **Truthfulness:** scope, posture, mode, availability, ownership, and authority
  match inspected artifacts. Prose is not evidence of execution.
- **Contract completeness:** semantic, machine, and conversational interfaces
  are present and internally consistent.
- **Placement and lineage:** the package is in the canonical scope tree and
  imported or adapted material has source and licence lineage.
- **Projection:** a clean rebuild—not a hand-edited generated file—produces the
  expected `<scope>:<skill-id>` entry.
- **Failure clarity:** missing inputs, unsupported requests, and unavailable
  dependencies are reported explicitly rather than fabricated or generalized.

## Additional gates for executable skills

- **Resolvable binding:** each operation has a stable unique ID and its declared
  module and callable import from the confined `source_root`.
- **Public-path test:** a realistic request executes through the same public API
  or CLI projected to the planner.
- **Negative-path test:** malformed or unsupported input fails closed and does
  not execute unintended code or providers.
- **Evidence quality:** tests assert meaningful outputs, receipts, or scientific
  invariants rather than only filenames, headings, or implementation wording.
- **No mock promotion:** mocks may test isolation or failure handling, but they
  cannot justify `availability: available` for a provider-bound operation.

## Additional gates for external data-source skills

- **Provider specificity:** provider identity, protocol, endpoint/operation,
  method, version expectations, and access constraints are reviewed.
- **Semantic coverage:** realistic natural-language cases cover aliases,
  colloquialisms, identifier forms, and at least one lexical gap while retaining
  entities, filters, fields, units, and source spans.
- **Native fidelity:** compilation produces a provider-native request or inert
  AST; harmonization never replaces the retained native payload.
- **Live proof:** at least one bounded real query reaches the admitted endpoint
  and records observed provider identity, execution status, native artifact,
  checksums, and provenance. Skips, fixtures, and mocks do not satisfy this gate.
- **Outcome distinctions:** success, valid no-hit, invalid input, access denial,
  rate limiting, and provider unavailability remain distinguishable.
- **Planner visibility:** both the skill operation and its source-reader/resource
  route appear in their generated indexes.

## Reject onboarding when

- a generated index is the only registration artifact;
- an executable operation points outside its declared source boundary;
- the description is broad enough to capture unrelated requests;
- provider execution is claimed from compilation, a fixture, or a mock;
- natural-language expansion drops scientific constraints;
- required validation or live evidence is skipped or stale.

## Acceptance report

For each gate, report `pass`, `fail`, or `not_applicable` plus a path, command,
test node, receipt, or generated identity as evidence. Any `fail` keeps the
onboarding status incomplete.
