---
name: workflow-reference-scout
description: Systematically scan the local skill and reference landscape whenever a new workflow is proposed, prioritizing existing workflow builders, package catalogs, database connectors, evidence layers, validators, and reporting skills before inventing new integrations.
---
<!--
SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>

SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
Neuro-symbolic AI Group

SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
Neuro-symbolic AI Group

SPDX-License-Identifier: Apache-2.0
-->

# Workflow Reference Scout

Use the authenticated selected package snapshot supplied by the host. Check exact
workflows and reusable workflow structures before nominating individual skills.
Treat names, scores, and graph summaries as discovery evidence only: read each
candidate's full instruction and interface contract before a reuse decision.

Inspect declared inputs and outputs, execution availability, authority limits,
source provenance, and report-control policies. Record unsupported operations and
missing bindings as gaps. A browse-only workflow is not executable.

Return `workflow_reference_scan` with the objective, selected context and snapshot
digest, workflow candidates, skill candidates, applicable package policies,
source/report references, and unresolved gaps. Every nominated item must come
from that snapshot. Do not search a checkout, home directory, or another package.
Planning does not execute workflows, acquire data, or install dependencies.

The host can call `lunar_planner.navigation.reference_scan(objective)`. The
[snapshot CLI](scripts/scan.py) accepts a host-provided JSON snapshot on stdin;
see [the input contract](references/snapshot-input.md).
