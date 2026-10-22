<!--
SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>

SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
Neuro-symbolic AI Group

SPDX-License-Identifier: Apache-2.0
-->
# Explicit snapshot input

Send a JSON object on stdin with `objective` (text), `context_identity`
(three nonempty strings: owner, package, version), and `surface` (the selected
`lunar.planner.surface-index/v1` navigation snapshot). Reuse review also takes
`candidate_ids`, a list of IDs present in this snapshot. The CLI is an offline
projection utility; the HTTP/MCP host authenticates and constructs these inputs.
An untrusted caller-supplied snapshot is not authentication evidence.

Output is JSON on stdout. No file paths, network requests, subprocess model calls,
or dependency installations are performed. Missing selection or candidate IDs
are errors. Candidate nomination is not execution or a semantic approval.
