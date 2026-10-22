<!--
SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>

SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
Neuro-symbolic AI Group

SPDX-License-Identifier: Apache-2.0
-->
# Skill capability profiles and runtime bindings

`SkillCapabilityProfile/v1` is the skill-owned, operation-level classification
contract. `RuntimeBinding/v1` describes how one operation can be reached. The
planner reads reviewed profiles and binding metadata, but owns neither.

Canonical schemas:

- `resources/schemas/skill-capability-profile-v1.schema.json`
- `resources/schemas/runtime-binding-v1.schema.json`

The controlled reasoning roles are `exact_transform`, `retrieval`,
`symbolic_solver`, `statistical_inference`, `numerical_simulation`,
`semantic_generation`, `human_judgment`, and `orchestration`. Execution
character is separately classified as `exact_deterministic`,
`numerically_deterministic`, `seeded_stochastic`, `stochastic_estimated`,
`provider_opaque`, `semantic_generative`, `human_variable`, or
`non_executing`. Semantic-generation disposition is a third independent field:
`required`, `conditional`, `optional_presentation`, `prohibited`,
`not_applicable`, or the release-blocking migration value `unknown`.

`authority` records approval and decision authority only. It never determines
reasoning role, execution character, generation disposition, binding, or
verification method. Whole-skill posture is derived from operations.

## Loading and planning

`lunar_planner.capability_profiles` provides strict validation, additive
sidecar loading, posture derivation, operation-specific verification selection,
and planning-only invocation compilation. A reviewed sidecar is applied only
when its `skill_digest` matches the current skill digest. Draft metadata is
advisory. Duplicate, stale, malformed, or digest-mismatched profiles fail
closed.

Runtime resolution uses only the existing
`lunar_planner.ports.RuntimeBindingRegistry`. The planner calls `resolve`
to inspect a descriptor; it does not import the entrypoint or execute scientific
work. Missing and unavailable bindings produce machine-readable remediation
tasks. They never route a computational claim to semantic generation.

The Lunar host composition attaches digest-matched reviewed profiles to
effective capability descriptors and configures `CatalogRuntimeBindingRegistry`
on `PlannerPorts`. `lunar_planner.plan_skill_operations()` is the public
configured-host entrypoint for compiling operation plans from those profiles.

Planned invocations carry `skill_digest`, `operation_id`,
`capability_profile_digest`, `binding_id`, `binding_digest`, execution
character, and the applicable verification methods. They are explicitly
`prospective`, `executed: false`, and have no observed receipt. Execution
systems must produce separate observed receipts.

## Generative and hybrid controls

Required or conditional generation must declare its evidence envelope,
provider and prompt provenance requirements, independent verification,
structured abstention, and no-self-approval rules in `generative_controls`.
Typed `handoffs` declare validation, immutable result anchors, propagated
epistemic fields, and human gates between operations.

## Prism isolation

Prism may consume reviewed exported metadata, but a Prism directory is rejected
as a capability-profile source. Removing generated Prism artifacts therefore
cannot alter skill classification, runtime resolution, or planner routing.
