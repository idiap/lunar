<!--
SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>

SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
Neuro-symbolic AI Group

SPDX-License-Identifier: Apache-2.0
-->
# Lunar planner

`lunar_planner` is Lunar’s internal planning module at
`app/backend/lunar_planner`. Its dependencies are managed by the repository-root
`pyproject.toml`. It
owns request normalization, candidate review, typed workflow drafts, independent
quality freezes, authority checks, provenance, continuation, and delivery
handoffs. It does not install or execute domain packages.

## Selected package context

A host must authenticate the owner, resolve one ready imported version, and bind
its immutable catalog through `PlannerConfig` and `PlannerPorts`. Missing
selection returns `selection_required`. The application adapter is
`app/backend/domain_packages/planning.py`; it obtains skills, workflows, reports,
and data sources from owned PostgreSQL records. A package declaring executable
planning policies requires an explicit worker-backed policy provider.

For Python commands launched from the repository root, set
`PYTHONPATH=app/backend` to import backend modules.

```python
from lunar_planner import run_planner_request
from lunar_planner.config import PlannerConfig, bind_planner
from lunar_planner.ports import PlannerPorts

class SelectedCatalog:
    def snapshot(self):
        return {
            "schema_version": "lunar.planner.surface-index/v1",
            "authority": "derived_navigation_only",
            "context_identity": ["owner", "inventory", "version-1"],
            "counts": {}, "skills": [], "workflow_packages": [],
            "subworkflows": [], "data_sources": [], "reports": [],
        }

with bind_planner(
    PlannerConfig(context_identity=("owner", "inventory", "version-1")),
    PlannerPorts(surface=SelectedCatalog()),
):
    result = run_planner_request("Build a warehouse inventory reconciliation workflow")
    assert result["executed"] is False
```

This example is an in-memory host fixture, not authentication. Production uses
server UUID identities and database ownership checks. Configuration and ports are
request-local. Continuations bind the owner, package, version, and snapshot;
a continuation cannot cross contexts even when both catalogs have identical
bytes. Opaque review/result/execution references remain server-owned.

There is no default catalog, parent-checkout discovery, or cross-package search.
Domain policies, source ecosystems, lexical routing adjustments, report
blueprints, and archetype definitions are supplied by the selected package.
Unavailable capabilities remain explicit gaps. Policy proposals do not confer
execution, network, installation, mutation, or release authority.

## Lifecycle and resources

The generic skills, profiles, schemas, and governance policies live with the module.
Exact route hints remain unselected until the independent outcome-quality
freeze. The delivery-quality plan has its own review and freeze. A successful
planning handoff is not an observed execution or a released report.

### Reusable post-plan reasoning verification overlay

Persistent workflow creation, extension, and refinement add a verification
sidecar after the initial immutable plan. Direct-use planning omits the stage.
The sidecar preserves the plan digest, distinguishes planned work from observed
evidence, and records bounded repairs. Verification readiness is not evidence
validation. See [the lifecycle contract](lifecycle/post-plan-reasoning-verification.md).

`lunar_planner.navigation.reference_scan()` nominates selected-version candidates;
`reuse_review_packet()` gathers their full imported contracts for semantic review.
Neither helper performs filesystem discovery, model subprocess execution, or an
automatic semantic approval. The packaged scout/review scripts accept an explicit
host-provided JSON snapshot on stdin.

The host controls runtime bindings, signature keys, clocks, quality evaluators,
artifact storage, and optional domain policies through typed ports. Filesystem
planner stores require an explicit version-specific state root. Completed-file
packaging requires separate write authority and is confined by the host to that
version's run artifacts.

## Verification

From the Lunar repository:

```bash
uv sync --locked --group mcp-backend
uv run --group mcp-backend pytest --run-expensive tests/planner tests/mcp_backend
uv run --group mcp-backend python planner/testing/verify_module.py
```

The module verifier copies the module outside the checkout, forbids application
and BioAgents imports, imports each top-level module, checks its resources, and
plans against a neutral inventory catalog using Lunar's Python environment.
Domain-specific benchmark drivers under `testing/domain_parity`
are retained migration oracles; they require selected imported-package bindings
and are not generic defaults or evidence of live execution.

The retained design/history documents describe the source lineage. This README,
the public typed ports, and the installed schemas describe the current ownership
and runtime boundary. BioAgents' scientific implementations belong to its
exportable package integration, not this module.
