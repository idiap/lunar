<!--
SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>

SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
Neuro-symbolic AI Group

SPDX-License-Identifier: Apache-2.0
-->
# Worked onboarding examples

Use the example matching the skill's real execution posture. Replace example
identities and bindings with inspected facts; do not copy availability or
provider claims speculatively.

## Example 1: instruction-only planner skill

Request: "Make our cohort-review playbook selectable by the planner. It does
not run code."

Choose `scope: planner`, `mode: instruction_only`, and `availability:
unavailable`. A minimal machine contract is:

```yaml
schema_version: bioagents.skill-metadata/v1
skill_id: cohort-review-guide
version: 1.0.0
scope: planner
role: planner
theme: planner
cluster: planner
structure:
  source_root: src
  tests_root: tests
  source_posture: instruction_or_orchestration_only
execution:
  posture: instruction_or_orchestration_only
  mode: instruction_only
  availability: unavailable
  implementation: null
```

Its `SKILL.md` should say when cohort review applies, what evidence it consumes,
what report it returns, and where its authority stops. Its default prompt should
explicitly invoke `$cohort-review-guide`.

Bad: declaring a fictional `execute` callable so the planner labels the guide
available. Better: represent the absence of runtime authority truthfully.

Acceptance evidence: validation succeeds and the generated surface contains
`planner:cohort-review-guide` with no executable operations.

## Example 2: repository-local executable skill

Request: "Onboard the package that compiles a typed cohort definition. Its
public Python entrypoint is `cohort_compiler.api.execute`."

After inspecting the importable package and callable, declare the binding:

```yaml
skill_id: cohort-definition-compiler
scope: scientific
execution:
  posture: reviewed_owned_source
  mode: native_python
  availability: available
  implementation:
    source_root: src
    module: cohort_compiler.api
    operations:
      - operation_id: cohort-definition-compiler:compile
        module: cohort_compiler.api
        callable: execute
```

The package should include `src/cohort_compiler/api.py`, an importable
`execute`, an executable wrapper such as `scripts/run.py`, and behavior tests
for successful and invalid requests. Test the same public operation exposed to
the planner, not a private helper.

Bad: using a module copied from upstream without lineage or review, or setting
`availability: available` because a README promises an implementation. Better:
inspect the owned source, preserve lineage, execute the public binding, and
record a truthful posture.

Acceptance evidence: the operation is statically resolvable, a realistic
invocation passes, invalid input fails closed, and the generated surface maps
`scientific:cohort-definition-compiler` to the exact operation binding.

## Example 3: external data-source query skill

Request: "Expose official DailyMed label search, including natural requests
such as 'show labels about aspirin'."

Use one provider-native operation per reviewed contract:

```yaml
skill_id: dailymed-source-query
scope: scientific
execution:
  posture: reviewed_owned_source
  mode: native_python
  availability: available
  implementation:
    source_root: src
    module: dailymed_source_query.runtime
    operations:
      - operation_id: dailymed-source-query:label-search
        module: dailymed_source_query.runtime
        callable: execute
        reasoning_role: provider_query
        execution_character: provider_bound
        semantic_generation_requirement: bounded
```

Add provider identity, HTTP method and operation path to the reviewed provider
contract. Add generative cases that bridge vocabulary without changing the
scientific entity:

```yaml
schema_version: bioagents.generative-cases/v1
cases:
  - id: colloquial-label
    query: show labels about aspirin
    operation: label_search
    expected_native: aspirin
  - id: routing-gap
    query: find drug labels for metformin
    operation: label_search
    expected_native: metformin
```

The runtime must execute the admitted provider read and return native payload
provenance and a receipt. A live content test must use the real endpoint; a mock
or fixture-only response does not establish provider availability. Keep the
original natural-language request and source spans so query expansion is
auditable.

Bad: routing every biomedical request to a generic search operation, silently
dropping filters, or treating a generated URL as a successful query. Better:
bind the request to a reviewed native operation, retain constraints, preflight
authority, execute the provider, and distinguish no-hit from unavailable.

Acceptance evidence: lexical-gap cases bind to the intended operation, invalid
fields fail closed, the live test records provider execution and native
artifacts, and the source-reader/operation indexes expose the skill.

## Before-and-after routing description

Before: `description: Queries databases.` This attracts unrelated work and
does not tell the planner which information need is supported.

After: `description: Search official DailyMed label metadata through a bounded
source-owned wrapper.` This identifies the source, record family, and boundary.

Before: `default_prompt: Run the tool.`

After: `default_prompt: Apply $dailymed-source-query to search official label
metadata; return needs_input or blocked when prerequisites are missing.`

These are patterns, not universal field values. The inspected implementation
and repository schemas remain authoritative.
