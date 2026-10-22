<!--
SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>

SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
Neuro-symbolic AI Group

SPDX-License-Identifier: Apache-2.0
-->
# Importing package versions

To convert a source repository into the format accepted here and exercise all
of its workflows, follow [Loading external projects](loading-external-projects.md).

`POST /api/packages/import` accepts an authenticated multipart request with one
`file` field containing a format-v1 ZIP. The session determines ownership; query
parameters and additional multipart fields, including owner overrides, are
rejected. Original filenames are ignored. Success returns HTTP 201 with the new
version identity, `status=ready` and `runtime_state=unprepared`.

`GET /api/packages/versions` lists the authenticated owner's ready versions.
`GET /api/packages/imports/{version_id}` returns that owner's import status,
including failed or staging attempts. Another owner's identity returns 404.
Each successful upload, including identical bytes, creates a separate version.
Validation never imports Python, installs a dependency or contacts source URLs.
Runtime preparation is a separate explicit operation.

## Storage and limits

Set `LUNAR_PACKAGE_STORAGE_ROOT` to a durable server-owned directory. The default
is `./var/packages`. Version directories use owner/package/version UUID segments.
Report/resource documents and original provenance bytes are stored in PostgreSQL;
Prism/runtime/support files, attachments and dataset bytes live in version
storage. Original historical identities and documents remain unchanged; fresh
navigation IDs are held in `package_import_mappings`. Imported historical runs
are never queued, and unknown historical workflows receive inert registrations.

The deployment can override these positive integer limits:

| Environment variable | Default |
| --- | ---: |
| `LUNAR_IMPORT_MAX_COMPRESSED_BYTES` | 2147483648 |
| `LUNAR_IMPORT_MAX_EXPANDED_BYTES` | 8589934592 |
| `LUNAR_IMPORT_MAX_FILE_BYTES` | 2147483648 |
| `LUNAR_IMPORT_MAX_MANIFEST_BYTES` | 33554432 |
| `LUNAR_IMPORT_MAX_DOCUMENT_BYTES` | 33554432 |
| `LUNAR_IMPORT_MAX_DIRECTORY_BYTES` | 67108864 |
| `LUNAR_IMPORT_MAX_ENTRIES` | 100000 |

The multipart reader enforces actual received bytes, finite headers and one
file. The ZIP reader bounds central-directory allocation before parsing it,
checks both declared and actual expanded lengths, and hashes streamed payloads.
Only bounded collection JSON documents are loaded into memory. Unsupported
compression, encryption, multiple volumes, prefixed/trailing ZIP data, unsafe
paths, duplicate names, links and special files fail before publication.

## Publication and recovery

Uploads begin under private `.uploads/upload-*` directories. Process leases
prevent startup cleanup from touching another server process's active upload.
Abandoned uploads are removed when startup recovery runs, including interruption
before any database version was allocated.

A session advisory lock protects each import. The service reserves a staging
version, writes all records in a PostgreSQL transaction, moves the validated
snapshot to the version's sibling staging directory, and publishes with a
same-filesystem rename before committing `ready`. Queries expose only ready
versions. Failures before commit roll back resource rows, remove inaccessible
bytes and mark the attempt failed. A failure after commit preserves the complete
version. If a connection dies with an uncertain commit result, files are retained
until recovery determines the database state.

Startup reconciliation skips active advisory locks, removes both staging and
uncommitted published directories for interrupted versions, and marks those
attempts failed. It never changes an already-ready version. Upload again to
create a new version after a failure; previous versions remain available.

Use matched PostgreSQL and package-storage backups. Container/volume deployment
and worker preparation are covered by the later operator/deployment transfer.
