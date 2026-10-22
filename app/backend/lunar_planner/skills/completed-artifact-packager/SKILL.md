---
name: completed-artifact-packager
description: Assemble generated files from a completed task into a deterministic delivery archive with an integrity manifest, one W3C PROV descriptor per file, and planner-level provenance. Use only when file-based delivery is requested or multiple user-facing files need consolidated delivery; never package partial work as final.
---
<!--
SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>

SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
Neuro-symbolic AI Group

SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
Neuro-symbolic AI Group

SPDX-License-Identifier: Apache-2.0
-->

# Completed Artifact Packager

Use this skill at the delivery boundary, after execution and quality checks—not
during ordinary planning.

## Admission

Package artifacts only when all of these hold:

1. The task has an evidenced terminal completion or release decision.
2. At least one generated file is supplied by the executing host.
3. The user requested packaged/file delivery, the host explicitly requests it,
   or completion produced multiple user-facing files that should remain together.

Otherwise omit packaging, or defer it until completion. Do not imply that a
planned artifact exists. Do not turn an informational answer into a file merely
to activate this skill.

## Package contract

Call the planner-native `build_delivery_package` boundary with the completed
planner result, explicit artifact paths, and an authorized output directory.
The returned ZIP must contain:

- the generated files without absolute host paths;
- `manifest.json`, including each file's SHA-256, media type, size, role, and
  archive path;
- one `provenance/<artifact-id>.prov.json` W3C PROV descriptor per file; and
- `provenance/planner.prov.json`, preserving the planner-level W3C PROV export.

Reject missing files, directories, symlinks, duplicate paths, and incomplete
tasks. Do not alter source files. Report the archive path and archive digest so
the conversational host can return a clickable package to the user.
Treat file bytes as observed package inputs. Unless retrospective execution
evidence names their producer, do not claim that the packaging activity or a
planned workflow generated those files; W3C PROV records package use and
membership separately from producer lineage.

## Completion criterion

Delivery is complete only when the archive is readable, every manifested file
matches its digest, every file has a provenance descriptor, and the returned
receipt is `ready_for_user`.
