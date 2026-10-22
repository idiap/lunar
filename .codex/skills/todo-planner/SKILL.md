---
name: todo-planner
description: Create a repository-grounded, dependency-ordered TODO.md implementation plan with concise task specifications, observable success criteria, and proportionate unit, integration, and opt-in end-to-end testing. Use when a user asks for an implementation plan or TODO list without implementing the change; do not use this skill to execute the plan.
---
<!--
SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>

SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
Neuro-symbolic AI Group

SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
Neuro-symbolic AI Group

SPDX-License-Identifier: Apache-2.0
-->

# TODO Planner

Produce an implementation-ready plan, not implementation. Write to the path
requested by the user, or to `TODO.md` when no path is given. Do not modify
product code, tests, configuration, or dependencies while planning.

## Ground the Plan

1. Read the applicable repository instructions and the smallest set of
   architecture, dependency, configuration, code, and test files needed to
   understand the current behavior.
2. Trace the relevant entrypoints and boundaries before naming changes. Reuse
   established modules, patterns, commands, and terminology.
3. Separate explicit requirements, evidence-backed facts, assumptions, and
   out-of-scope work. If there are conflicting instructions or underspecified
   requirements, stop and ask me. Ask before writing when an unresolved choice
   would materially change the architecture or acceptance result.
4. Preserve an existing unrelated planning document. Do not replace or merge
   it silently.

Name concrete files or symbols only when repository evidence supports them.
Otherwise name the responsible component or boundary and make discovery the
first bounded task. Do not invent paths, APIs, commands, or current behavior.

## Design the Work

- Choose the smallest change that satisfies the request and follows the
  existing architecture. Prefer a direct solution using existing code; add
  complexity only when a concrete requirement makes it necessary.
- Limit planned edits to surfaces needed for the goal. Exclude adjacent
  refactoring, formatting, cleanup, speculative features, and future-proofing.
  Remove only code made unused by the planned changes; report unrelated
  issues separately without turning them into tasks.
- Split work into dependency-ordered phases proportionate to the goal; a
  small change may need only one phase and one task. Give every task a stable
  ID and list its exact prerequisite task IDs or `None`.
- Give each task one independently verifiable outcome. State the behavior to
  add or change, the responsible surface, and any important boundary or
  non-goal.
- Put contract, schema, or interface changes before their consumers. Put
  implementation before integration and final verification.
- Keep code cohesive and files focused, but do not invent abstractions,
  configuration, fallback paths, compatibility layers, or numeric file-size
  limits without a demonstrated need.
- Replace vague instructions such as "wire it up", "handle edge cases", or
  "add tests" with exact behavior and observable results.

## Specify Verification

- Define success criteria as externally observable outcomes: returned values,
  persisted state, rendered states, emitted artifacts, errors, or preserved
  behavior. Avoid criteria such as "works", "is robust", or "is clean".
- Add the narrowest meaningful tests beside the task that introduces the
  behavior. Include ordinary unit tests for logic and failure boundaries, and
  integration tests only where component interaction is part of the contract.
- Reuse existing coverage when it already proves a success criterion. Add or
  change tests only to close relevant coverage gaps; do not expand test
  infrastructure without a demonstrated need.
- Derive test locations, markers, and commands from the repository's existing
  test configuration. Record the exact default test command in the plan.
- Require end-to-end tests when the user requests them or when only a real
  cross-boundary path can prove the critical behavior. They must exercise the
  supported application, workflow, or provider path; fixtures may stabilize
  inputs, but mocks must not replace the boundary being verified.
- Mark end-to-end tests with the repository-native mechanism and exclude them
  from the default test command. State a separate exact opt-in command. A
  skipped or unrun required end-to-end test is not completion evidence.
- Map every success criterion to an automated test or, only when automation is
  unsuitable, a precise manual inspection. Do not substitute manual checks for
  automatable behavior.
- Require regression coverage for behavior that must remain unchanged. Do not
  add tests that merely assert implementation details, wording, or file
  existence when behavior can be tested.

Passing the full planned verification set must be sufficient to show that the
requested behavior is complete. If tests cannot establish a required outcome,
the plan must name the additional verification instead of overstating coverage.

## Write `TODO.md`

Use this compact structure and omit empty sections:

```markdown
# TODO: <requested outcome>

## Goal
- <one observable end state>

## Scope and assumptions
- <requirement, resolved interpretation, constraint, or non-goal>

## Dependency order
`T01 -> T02 -> T03`

## Phase 1 — <outcome>

- [ ] **T01 — <imperative task title>**
  - Change:
    - <exact behavior and responsible surface>
  - Dependencies: None
  - Tests:
    - <test case and exact command or suite>
  - Success criteria:
    - <observable pass condition>

## Final verification
- [ ] <default test command and expected result>
- [ ] <opt-in end-to-end command and expected result, when required>
- [ ] <manual acceptance check, only when needed>
```

Keep bullets concise, but include enough detail that an implementer does not
need to rediscover intent, dependency order, test isolation, or the definition
of done. Do not include implementation snippets unless a signature, schema, or
command is necessary to remove ambiguity.

## Completion Check

Before handing off the plan, confirm that:

- every user requirement appears in at least one task and success criterion;
- every task traces to the requested outcome and has unambiguous dependencies;
- every planned edit and added mechanism is necessary to meet a requirement
  or verify it; remove work whose omission would still satisfy the goal, and
  simplify any approach that has an equally correct, smaller alternative;
- ordinary tests run by default and required end-to-end tests run only through
  the documented opt-in command;
- the final verification covers new behavior, failures, integration points,
  and required regressions; and
- no unresolved placeholder, silent assumption, or implementation work remains
  hidden inside the plan.

## Example Request

Create a `TODO.md` plan for integrating a local service into an existing
application. Require a configured provider selection before execution, add
ordinary unit tests, and add opt-in end-to-end tests that exercise each
existing workflow. Do not implement the changes.
