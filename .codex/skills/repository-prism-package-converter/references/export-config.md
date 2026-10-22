<!--
SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>

SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
Neuro-symbolic AI Group

SPDX-License-Identifier: Apache-2.0
-->
# `prism-export.json` contract

The deterministic exporter consumes UTF-8 JSON. Paths are repository-relative, may not escape the repository, and may not traverse symlinks. Arrays are explicit to prevent heuristic discovery drift.

```json
{
  "schema_version": 1,
  "package": {
    "key": "repository-slug",
    "display_name": "Repository workflows"
  },
  "python": ">=3.12,<3.15",
  "skills": [
    {
      "id": "stable-skill-id",
      "name": "Stable skill name",
      "root": "skills/group/stable-skill-id",
      "description": "What the skill does",
      "groups": ["group"],
      "capabilities": [],
      "exclude": []
    }
  ],
  "data_sources": [
    {
      "id": "contracts",
      "name": "Repository contracts",
      "paths": ["contracts"],
      "prefix": "contracts",
      "descriptor": {"kind": "contract-registry", "trust": "canonical-source"},
      "remote_references": [],
      "exclude": []
    }
  ],
  "workflows": [
    {
      "id": "workflow-id",
      "name": "Workflow name",
      "root": "repository-prism/projects/workflow-id",
      "entrypoint": "prism_project/material_main.prism",
      "reasoning_entrypoint": "prism_project/main.prism",
      "description": "Complete workflow behavior",
      "public_output_type": "Disposition",
      "semantic_mode": "operational",
      "skill_ids": ["stable-skill-id"],
      "metadata": {
        "provenance_note": "Runtime expectations belong in the material entrypoint metadata.provenance_contract"
      }
    }
  ],
  "runtime": {
    "requirements_lock": null,
    "planning_hooks": [],
    "entrypoints": [
      {
        "id": "repository-workflow-execute",
        "operation": "execute",
        "source": "repository-prism/runtime/runtime.py",
        "target": "runtime.py",
        "callable": "execute"
      }
    ]
  },
  "exclusions": []
}
```

`skills`, `data_sources`, and `workflows` are sorted by `id` by the exporter, but the source file SHOULD already be sorted for reviewability. IDs must be unique within their collection. Every `skill_ids` reference must resolve.

`workflows[].skill_ids` declares package dependencies; it is not a runtime activation receipt. Put expected ordered agent/skill activations and required source reads in the material entrypoint's `# lunar-runtime:` `metadata.provenance_contract`. The live validator compares that contract to the persisted run API.

All files under each declared root/path are included except standard transient names and explicit `exclude` globs. If a data-source path is a file it is included directly. If it is a directory, its complete recursive contents are included.

Canonicalization is extension-based:

- `.json`: parsed and emitted as canonical JSON;
- `.yaml`/`.yml`: safely parsed and emitted with sorted keys;
- recognized text formats: UTF-8, NFC, LF endings, one terminal newline;
- other files: exact bytes.

The exporter adds a content-addressed conversion lock and validates the completed archive with the selected Lunar checkout. `--verify-reproducible` performs a second independent export and compares the complete ZIP bytes.
