# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Safe Prism run response serialization."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from modules.common import json_value, record_json


def serialize_run(
    row: Mapping[str, Any],
    relations: dict[str, list[Mapping[str, Any]]] | None = None,
) -> dict[str, Any]:
    result = record_json(row)
    result["safe_inputs"] = json_value(result.pop("safe_input_manifest", None), {})
    result.pop("mode", None)  # Retained only as a constant legacy database column.
    result["ai_model_snapshot"] = json_value(result.get("ai_model_snapshot"))
    for key, values in (relations or {}).items():
        result[key] = []
        for value in values:
            item = record_json(value)
            if key == "events":
                item["detail"] = json_value(item.get("detail"), {})
            if "redacted_metadata" in item:
                item["redacted_metadata"] = json_value(item["redacted_metadata"], {})
            if "binding_metadata" in item:
                item["binding_metadata"] = json_value(item["binding_metadata"], {})
            if "structured_value" in item:
                item["structured_value"] = json_value(item["structured_value"])
            if "detail" in item:
                item["detail"] = json_value(item["detail"], {})
            if key == "artifacts":
                item["url"] = (
                    f"/api/prism/runs/{result['id']}/artifacts/{item['id']}?package_version_id={result['version_id']}"
                )
            result[key].append(item)
    result.pop("artifact_root", None)
    return result


def serialize_reasoning(row: Mapping[str, Any]):
    from prism_runs.reasoning import ReasoningEntry

    item = record_json(row)
    item.pop("user_id", None)
    item.pop("version_id", None)
    item["source"] = json_value(item["source"], {})
    item["presentation"] = json_value(item["presentation"], {})
    return ReasoningEntry.model_validate(item).model_dump(mode="json")
