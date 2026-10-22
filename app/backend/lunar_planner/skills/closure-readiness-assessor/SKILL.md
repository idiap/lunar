---
name: closure-readiness-assessor
description: Decide whether a live planner state warrants a user-facing next-step suggestion by locating a concrete unresolved input, review, acceptance, repair, or gap obligation. Use near the end of a planning turn; omit suggestions when the request is closed, denied, merely informational, or lacks an actionable closure target.
---
<!--
SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>

SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
Neuro-symbolic AI Group

SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
Neuro-symbolic AI Group

SPDX-License-Identifier: Apache-2.0
-->

# Assess whether planning needs a next step

Inspect the current planner receipt rather than inferring work from the topic.
Return `suggest` only when one observable obligation prevents the current plan
from advancing or closing. Classify that obligation as one of:

- missing user input;
- independent quality or semantic review;
- acceptance of an exact digest-bound handoff;
- localized repair with a named failing target;
- review of an explicit capability gap.

Return `omit` when the request is complete, denied, a help/listing response,
or when the only possible suggestion is generic exploration, an optional
adjacent task, or an action outside current authority. A blocker is not by
itself a useful next step: require an identifiable object, action, and closure
condition.

Output a closure state, disposition, reason, and the identifiers of the
unresolved obligations. Do not claim that planned work ran, invent missing
user intent, expose hidden reasoning, or turn a recommendation into approval.
