<!--
SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>

SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
Neuro-symbolic AI Group

SPDX-License-Identifier: Apache-2.0
-->
# External data-source planning

The `external_data_source_planning` phase turns an ordinary biomedical need
into an `ExternalSourcePlanningPacket@v1`. It runs after problem/outcome framing
and before capability or pipeline design. It is planning-only: source network
access, installation, mutation, download, and KB capture are forbidden.

The phase emits ordered data needs, calls the canonical source-query planner for
each need, embeds the corresponding complete portfolio receipt, and describes
an acquisition DAG plus typed consumer handoffs. Resource, access point,
operation, connector, and consumer remain separate. Unavailable, unauthorized,
partial, stale, and truncated routes are never reported as biological no-hits.

Activation is based on an external evidence dependency such as literature,
trials, cohorts/files, expression, variants, compounds, pathways,
interactions, structures, cell atlases, proteomics, or metabolomics. A purely
local transformation or a request explicitly limited to supplied inputs is a
typed no-op. Ordinary direct source questions use the `external_data_query`
route and return a dry-run `SourceQueryPlan@v1`.

The committed `catalog/data_sources/index.json` is runtime truth. Reference ZIP
archives are import inputs only and are never read by planner/runtime code.
Catalog digest changes create a new packet rather than mutating an accepted one.

Rollback disables the reusable stage and optional packet reference. Catalog
search and per-query dry-run planning remain available independently.
