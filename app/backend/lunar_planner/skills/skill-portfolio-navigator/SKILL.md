---
name: skill-portfolio-navigator
description: Navigate the selected package skill portfolio from a clean context, shrinking a large capability space into the few workflow-relevant skills, routes, and blind spots that should drive reuse before new skills are proposed.
---
<!--
SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>

SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
Neuro-symbolic AI Group

SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
Neuro-symbolic AI Group

SPDX-License-Identifier: Apache-2.0
-->

# Skill Portfolio Navigator

Use this at the start of a new workflow or a major pipeline refinement.

Read the selected version's workflow registrations, skill documents, data-source
descriptors, and report lineage through the authenticated host. Treat only its
admitted resources as workflow candidates. Generic planner skills govern the
process and may be selected as explicit control routes.

For broad objectives, call `lunar_planner.navigation.reference_scan(objective)`
or the workflow-reference-scout snapshot helper. Read each nominated candidate's
full imported instructions and interfaces before a semantic reuse decision.

## Goal

Convert a very large skill portfolio into a small, workflow-specific capability packet.

This skill narrows the candidate set. It does not make the final reuse decision. For comprehensive planning, hand the packet to `skill-reuse-critical-reasoner`, which must review candidate skill bodies through the host's configured semantic review mechanism.

## Output Contract

Emit one `skill_portfolio_packet` with:

- `objective`
- `recommended_routes`
- `workflow_family_candidates`
- `relevant_local_skills`
- `selected_context`
- `snapshot_digest`
- `likely_composition_paths`
- `high_risk_blind_spots`
- `first_pass_read_order`
- `semantic_review_handoff`

Each listed skill should include:

- `skill`
- `source`
- `path`
- `why_relevant`
- `why_full_body_review_needed`

## Rules

- Prefer the smallest believable reusable subset of the portfolio.
- Preserve imported lineage while admitting only capabilities in the selected version.
- Surface likely blind spots, but do not declare true capability gaps yet.
- Do not treat keyword overlap, route membership, or frontmatter descriptions as proof of fit.
- If the work affects a paper, mechanism claim, external evidence, or new skill creation, hand off to `skill-reuse-critical-reasoner` for content-based classification.
- If the selected package lacks an applicable capability, record the gap; propose an external discovery step only when a selected package policy supports it and the caller authorizes it.
