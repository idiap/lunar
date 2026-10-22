<!--
SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>

SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
Neuro-symbolic AI Group

SPDX-License-Identifier: Apache-2.0
-->
# Selected package APIs

Resource routes require an authenticated user and one owned, ready package version.
Send `X-Lunar-Package-Version: <version UUID>` or use `package_version_id` in a
protected link. Duplicate or conflicting selections fail. MCP uses the same
selection with its bearer token. The context stays bound until streaming finishes.

Skills, data sources, repository catalogs/graphs, report history, workflow runs,
provenance, artifacts and reasoning subscriptions use that selection. File URLs
contain server-generated identities and the version query parameter. File bytes
are checked against imported or worker-recorded digests before delivery.
Repository assets are declared through a repository resource's `metadata.catalog`
and `metadata.bundle` linked file paths; source files use the resource's file IDs.
If multiple resources declare an asset, select its logical `repository_id`.

A new chat records the current version. Listing, reopening, saving or deleting a
chat requires its original selection. Chats without package context remain
available without a selection. Changing a selection never retargets an existing
chat or background run. Opaque planner continuations are bound to their original
owner/version and expire when the API process restarts.

The `planner` MCP tool accepts an optional owned `ai_model_id` for workflow model
calls. Chat supplies its selected model automatically. Planning-only requests do
not execute. The planner freezes and reviews both quality plans, executes only a
registered workflow that is ready to produce evidence, and submits its verified
candidate to the final quality gate. A successful worker run alone does not
publish a conversational report. Failed runs retain raw observations and any
validated failure artifacts; they cannot produce a released output.

For stdio, configure `LUNAR_STDIO_USER_ID`, `LUNAR_STDIO_VERSION_ID`,
`DATABASE_URL`, and `LUNAR_PACKAGE_STORAGE_ROOT`. The configured owner must own
the selected ready version. Stdio returns released artifacts with publication
unavailable; the local configuration does not supply an authenticated publication
identity. HTTP/MCP publication requires the verified user identity.

Imported runs stay historical and are never resumed. Their original timestamps,
source/input observations, stage records, provenance and artifact bytes remain
inspectable. Pending imported reasoning presentations are marked interrupted;
original documents remain in the package resource and file inventory.

The workspace validates the remembered per-user selection against owned versions
before mounting package views. Switching versions clears graph caches and discards
late responses. An existing chat's owner-only `/api/chats/{id}/context` lookup
returns its version binding before content is read. A switched-away running chat
continues consuming its original stream without navigating or updating the new
workspace.

`POST /api/packages/versions/{id}/prepare` explicitly prepares an owned runtime
using the operator's `LUNAR_WORKER_IMAGE`. It accepts no caller image or ownership
overrides. Status and failures are exposed in the version list; browsing does not
prepare dependencies. Workflow metadata may declare `viewer_workflow_id` to group
operations in a reviewed graph and `model_required: true` to require a configured
model. Generic workflows accept their declared JSON inputs without graph assets.

The workspace's Export ZIP link downloads one owned version through
`GET /api/packages/versions/{id}/export`. Export reads a repeatable, read-only
PostgreSQL snapshot, verifies source file digests and source stability, then
publishes a complete ZIP. Current edits, authoritative revisions, attachment links,
report sections, template snapshots, and referenced run/output observations travel
with the package. Deleted reports and unrelated runs, accounts, chats, credentials,
and editable templates do not. Historical accepted-input/provenance identities
remain evidence and never become the importing owner's execution authority.

A completed `package_exports` receipt records owner/version, source archive digest,
snapshot timestamp and output digest. Download headers expose the receipt ID and
snapshot timestamp. Temporary ZIP bytes use the same process leases and abandoned
workspace recovery as uploads; response completion/disconnection releases them.
A re-import always allocates a new owned version and requires separate runtime
preparation. A template-generated report remains immutable after import.

The Prism workspace can also export one selected source-derived workflow through
`GET /api/packages/versions/{version_id}/workflows/{workflow_id}/export`. This is
an evidence ZIP, not an importable domain package. It contains the exact PRISM
source closure, the server-derived visualization as JSON and standalone SVG,
executable binding metadata,
matching run summaries, and every stored PROV-JSON and JSON-LD document for those
runs. Its manifest records the source version, repeatable-read snapshot time, and
SHA-256 inventory; unrelated workflows and runs are excluded.
