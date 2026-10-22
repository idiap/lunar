<!--
SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>

SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
Neuro-symbolic AI Group

SPDX-License-Identifier: Apache-2.0
-->
# Domain package archive v1

This is the canonical Lunar interchange contract. The pinned exporter copy is
byte-for-byte identical and validates offline. Format version `1` and worker
contract version `1` are independent of a server-assigned imported version.
There is no default domain, biological vocabulary, role hierarchy or source-root
search in this format.

## Archive layout and identities

A ZIP contains root `manifest.json` and the four directory entries `repository/`,
`reports/`, `skills/`, `data-sources/`. Empty collections are valid. All other
entries are regular files listed exactly once in `manifest.files`, with a
canonical archive-relative path, byte length, media type and lowercase SHA-256.
The manifest itself is not in its own payload inventory. ZIP names use NFC,
forward slashes and no empty, dot, parent, absolute, drive, control-character,
reserved-device or trailing-dot/space segments. Case-insensitive collisions and
file/directory collisions are invalid. Symlinks, special files, encryption,
unsupported compression and non-regular entries are rejected by the archive
reader. Deployment supplies finite compressed/expanded byte and entry limits;
readers enforce them while consuming streams, including actual expanded lengths.

`manifest.package.key` is a stable package identity; `display_name` is presentation
text. The manifest contains no user, imported version, account secret or live
session. Each successful upload allocates a new monotonically increasing version
inside the authenticated owner's package, even for identical archive bytes.
Logical resource IDs are unique only within one collection of that version.
An importer allocates fresh database IDs and keeps a separate mapping from
original collection/ID to local ID. Re-export omits local authority and a new
owner can import the same logical IDs safely. Package/version context is immutable
for existing chats, planner continuations, runs, report bindings and subscriptions.

Each collection entry has `id`, `document`, `files` and `references`.
`document` names its JSON resource record in the matching archive directory.
`files` lists its supporting payloads, which may share a single physical manifest
entry with other resources. `references` explicitly names collection/ID edges.
Repeated logical references to identical bytes retain their distinct identities.
Every target must exist. Repository metadata may retain domain-specific graph
properties; operational files are always addressed through declared file entries.

The machine-readable schemas in `app/backend/domain_packages/format/` are
normative. `validate_manifest` checks structure, identity, references and runtime
compatibility. `validate_payloads` additionally checks exact bytes and collection
records. Neither runs Python payloads, resolves remote schemas, downloads data nor
prepares dependencies. Archive extraction/publication is a separate service.

## Collections and storage destinations

| Archive location | Required contents | Lunar destination |
| --- | --- | --- |
| `repository/` | Complete PRISM project/module source trees, runtime Python packages, dependency lock and policies | Version-segmented files; repository/workflow metadata in PostgreSQL |
| `reports/` | Report JSON records, current text/version, available prior revisions, attachment bytes, section lineage, linked historical run/output facts and original provenance documents | Text, lineage and original provenance in PostgreSQL; attachments in version storage |
| `skills/` | Skill JSON records with full instructions, capability/invocation metadata, optional grouping labels, source/support files and non-text assets | Instructions/metadata in PostgreSQL; non-text and runtime assets in version storage |
| `data-sources/` | Descriptor JSON records, local-file identities and bytes, remote references | Descriptors/file metadata in PostgreSQL; local dataset bytes in version storage |

Every referenced local dataset and report attachment must be readable and stable
at export. Missing local bytes are an explicit failure, never an empty stand-in.
A local operational path becomes the `file` archive reference on a local-file or
attachment record; the original authoring location may remain only as historical
provenance. Remote references are preserved without fetching their datasets.
Remote locators must not carry credentials. Credentials, editable account prompts,
templates, model connections, sessions and unrelated historical runs are excluded.

Report sections reference output facts in that report's `outputs`; each output
references a `runs` fact. Include the full report-linked closure even when a run
is shared between reports. `template_snapshot` carries historical section/template
facts and digests, never an editable account template. `provenance` identifies the
original PROV-JSON and/or JSON-LD payload and its exact digest. Keep those bytes
unchanged; import-navigation ID mappings are separate records. Historical signed
receipts remain historical assertions, not execution permission or a new Lunar
attestation. Available prior revisions have distinct version numbers below the
current version; never synthesize missing historical text.

An exporter reads a repeatable-read, read-only PostgreSQL snapshot for exactly one
requested source owner, verifies source file digests/stability, constructs all
payloads and validates the completed package before atomic ZIP publication.
Requesting saved reports cannot silently degrade to a database-free export.
Lunar re-export applies the same rule to one selected ready version and its current
saved report closure. Original import/source provenance is preserved; export
snapshot facts are additional metadata, not replacements for original documents.

## Runtime and planner boundary

`runtime.contract_version` is 1. `runtime.python` is a PEP 440 compatibility
specifier. `requirements_lock`, when present, points inside `repository/` and
pins the package environment, including its complete scientific dependencies.
Runtime preparation is an explicit operation in an isolated version-specific
container. Upload does not install anything into the API process. Dependency
fetching during preparation is permitted; an offline dependency mirror is not
required. Unavailable dependencies produce a visible preparation failure.

`entrypoints` registers package-relative Python files and a single function name
for `prepare`, `plan` or `verify`. They are declarations, not server import paths.
The worker adds only the mounted package runtime roots to its import path.
Every linked PRISM `reasoning` block is a selectable workflow view and must be
paired with a materialized executable `workflow` declaration. Reasoning supplies
the visualization; execution always uses the paired material implementation.
`runtime.workflows` and repository `metadata.bundle`
are forbidden. The platform generates the viewer response deterministically
from source; packages cannot override its nodes or edges. Required
`# lunar-runtime:` JSON comments bind actual executable declarations to worker
hooks, input/output schemas, and execution metadata. A workflow has one execution
contract; reasoning and materialization are not execution modes. Packages with an
unpaired reasoning block are rejected. See [the source projection contract](../app/backend/domain_packages/format/VISUALIZATION.md)
for the annotation fields and legacy export migration.
`planning_hooks` names explicit plan hooks; omission never activates a built-in
domain provider. Offline validation requires the pinned PRISM language parser.

### Input presentation

Run forms use the workflow input schema and preserve its validation contract.
Supply JSON Schema `title`, `description`, `default`, and `examples` to guide
users. Use `enum` or `oneOf` with `const` and `title` for closed, supported
choices (for example, named policies). Examples are suggestions, not an
allow-list. The platform does not invent policies, backends, or revision IDs.

String fields may carry an optional, domain-independent `x-input` annotation:

```json
{
  "type": "string",
  "title": "Source document",
  "x-input": {
    "kind": "file",
    "extensions": [".tex", ".pdf"],
    "pathPrefix": "repository/sources/",
    "relativeToPrefix": false,
    "placeholder": "Select a source document"
  }
}
```

Supported kinds are `text`, `textarea`, `file`, `reference`, and `digest`.
These are presentation hints; they do not add validation restrictions.
`file` and `reference` browse the authenticated, selected version's imported
file inventory. `reference` leaves the selected path editable so users can add
the source's declaration or line syntax. Paths are archive-relative unless the
package explicitly sets `relativeToPrefix: true`, which removes `pathPrefix`.
`digest` copies the chosen file's recorded SHA-256, prefixed with `sha256:` by
default; a bare digest is used if only that form passes the field's schema.
`digestPrefix: ""` explicitly selects a bare digest. A file checksum is not an
aggregate registry or run digest. File availability does not establish semantic
suitability for a workflow; packages must define any stronger constraints.

For older packages without annotations, names ending in `_path`/`_paths`,
`_anchor`/`_anchors`, and `_digest` offer the corresponding picker. Context,
scope, criteria, derivation, description, instructions, prompt, and goal fields
use multiline text. Explicit `x-input.kind` overrides these conventions.
String arrays support ordered item editing, bulk paste (one item per line),
and file selection using the array's hints. Arrays of formatted strings, enums, objects, and union
schemas keep the standard schema renderer. Validation still enforces item
constraints, uniqueness, and array bounds.

The run dialog can reuse schema-valid inputs from its recent completed runs
in the same package version, workflow, and mode. Values from these runs and
schema examples are offered as labeled suggestions and remain subject to the
current schema. Users must review references for the new run. No package
manifest or imported payload is modified to provide these controls.

`GET /api/package-files?query=...&prefix=...&extensions=.tex,.pdf` returns at most
40 inventory matches with canonical paths, checksums, and protected download
links. `has_more` indicates that the search should be narrowed. Searches are
literal, bounded, and scoped by the normal package selection and ownership
checks; the endpoint does not browse the server filesystem or execute package
code.

The selected ready version supplies the planner's capability catalog, invocation
metadata, workflow/archetype descriptions, report/source references and policy
records, adapting the existing typed planner ports. Executable domain planning
providers cross the worker boundary. Generic lifecycle, quality and authority
checks stay host-owned. Planning-only calls cannot execute workflows, acquire
sources or prepare dependencies; absent selection/capability returns an explicit
selection-required/unsupported outcome.

The JSON worker request/result schemas are the wire contract. A request carries
a host-generated opaque `request_id`, operation, workflow/hook identity, validated
input and narrow network/model authority. Owner/database credentials and the web
server environment never enter this message. The host mounts only the selected
version's inputs read-only and that run's output directory writable, without a
host socket, other versions or other users. Provider access is mediated by a
scoped host boundary. Package hooks cannot manage container lifecycle.

Preparation returns the existing `PreparedPrismInput` fields: entry argument name,
JSON value, request digest and analysis results. The host runs the real Prism
compiler/runtime with that argument. Execution returns the existing result fields:
markdown, typed structured value, analysis results, compact input, narrative slots
and report verification. Events have monotonically increasing sequence numbers
and identify stage, input, source, artifact, provenance or public reasoning facts.
Artifacts declare run-relative paths, lengths, media types and SHA-256. Worker
failure/interruption returns a terminal status, error stage/code/message, and
available partial events/artifacts. It never yields a successful released report.

The platform validates returned schemas, paths, digests, source/owner context,
event sequencing and release decisions before persistence. A successful hook is
not by itself authorization to release: existing host quality and provenance
checks still apply. Imported historical receipts do not satisfy a new run's
observed execution requirements.

## Import publication and recovery

The host derives ownership exclusively from session/MCP authentication. It stages
validated files under server-generated owner/package/version path segments and
creates all records and logical-ID mappings transactionally. Versions have
staging/ready/failed states. Only ready versions are readable. Filesystem publish
uses a same-filesystem rename; a database transaction is not a file rollback.
Recovery reconciles crashes before/after rename and commit, removes inaccessible
failed staging bytes and never changes existing ready versions. Concurrent uploads
serialize version allocation in PostgreSQL. No archive-supplied value chooses an
absolute host path, owner or imported version.
