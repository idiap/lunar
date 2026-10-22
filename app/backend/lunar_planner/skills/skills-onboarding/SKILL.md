---
name: skills-onboarding
description: Onboard skills from other projects into the Lunar planner by defining, validating, and projecting their semantic, executable, and conversational registration interfaces.
---
<!--
SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>

SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
Neuro-symbolic AI Group

SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
Neuro-symbolic AI Group

SPDX-License-Identifier: Apache-2.0
-->

# Skills Onboarding

Use when authoring or inspecting a domain package whose capabilities must become
discoverable in Lunar. Work against domain-package format v1 and the selected
package version; a skill directory on the host is not an installed capability.

Require a stable skill ID, name, complete instructions, capability descriptors,
invocation contract, optional groups, and declared asset references in the skill
resource document. Executable operations require package runtime bindings,
explicit inputs/outputs and authorities, and worker preparation. Instructions or
an import success alone do not establish executable availability.

Validate the complete ZIP inventory, hashes, references, and runtime registration.
Preserve source/licence lineage. Import creates a new version; verify its owned
skill records and planner candidates without overwriting the previous version.
Exercise declared operations only through the host worker boundary with separate
execution authority. Report unavailable dependencies or missing bindings honestly.

Return the source lineage, package/version identity, imported resource IDs,
contract and reference validation results, planning visibility, declared runtime
availability, unresolved findings, and the verification performed. A planning-only
capability can be discoverable while remaining non-executable.
