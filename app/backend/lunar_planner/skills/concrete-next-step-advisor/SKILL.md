---
name: concrete-next-step-advisor
description: Convert an admitted unresolved planner obligation into one concrete, closure-oriented user action with named inputs, expected evidence, completion criteria, and authority boundaries. Use only after closure-readiness-assessor returns suggest; do not add generic optional follow-ups.
---
<!--
SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>

SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
Neuro-symbolic AI Group

SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
Neuro-symbolic AI Group

SPDX-License-Identifier: Apache-2.0
-->

# Recommend one concrete next step

Choose the earliest high-priority obligation that can materially advance the
current plan. Prefer, in order: required user input, mandatory review, exact
handoff acceptance, earliest localized repair, then explicit gap review.

Produce one primary suggestion unless independent actions are genuinely needed
before the plan can advance. Each suggestion must state:

- the exact action and target identifier;
- why it is the next closure dependency;
- the input or authorization still required;
- the artifact or evidence expected from the action;
- an observable completion criterion;
- which open obligation it closes; and
- the authority ceiling, including when a separate approval is required.

Reuse planner-native operations when one exists, such as reviewing a quality
plan or accepting a digest-bound handoff. Phrase user questions in outcome
language rather than internal skill terminology. Never suggest unrelated
analysis, “explore further,” rerunning already verified work, or external
mutation merely to keep the conversation going.

Examples:

- After quality criteria are synthesized: review and freeze the named quality
  contract; closure is reached when its review status is accepted.
- After a failed workflow test: repair the named earliest failing node and
  rerun only its invalidated test set.
- After a complete capability listing: emit no suggestion.
