---
name: skill-reuse-critical-reasoner
description: Critically audit and orchestrate Lunar skill reuse before workflow planning, external evidence selection, manuscript updates, or new skill creation. Use when a workflow must be comprehensive from the start, maximize reuse, prevent missed prior skills, define systematic external-evidence criteria, or decide whether new skills are truly needed.
---
<!--
SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>

SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
Neuro-symbolic AI Group

SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
Neuro-symbolic AI Group

SPDX-License-Identifier: Apache-2.0
-->

# Skill Reuse Critical Reasoner

Use the selected package catalog to review reuse before composing or changing a
workflow. Search results nominate candidates; a content-based review decides
whether their full contracts cover the requested outcome.

Read candidate instructions, input/output interfaces, authority, dependencies,
availability, and provenance. Compare direct reuse, composition, adaptation, and
an explicit capability gap. Explain rejected alternatives. Preserve claim limits,
independent quality reviews, and the selected package's report-control obligations.
For a report revision, bind the prior report and new evidence from the same
version and identify affected claims, sections, figures, and release checks.

Return `reuse_critical_packet` with the objective, context and snapshot digest,
reviewed candidate identities and content digests, coverage and limitations,
reuse classification, unresolved obligations, and a bounded next action.
Do not invent missing capabilities or authorize implementation from a nomination.

The host can call `lunar_planner.navigation.reuse_review_packet(objective, ids)`
to gather complete imported candidate instructions. It returns a packet requiring
semantic review, never a fabricated review verdict. The [snapshot CLI](scripts/review.py)
accepts the host-provided input described in [the contract](references/snapshot-input.md).
Do not scan other repositories or invoke a local model CLI from this helper.
