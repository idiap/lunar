# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Serialization for canonical skill summaries and details."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import PurePosixPath
import re
from typing import Any

from modules.common import record_json, json_value

ABSOLUTE_PATH = re.compile(r"^(?:/|file://|[A-Za-z]:[\\/])")
SUMMARY_FIELDS = (
    "skill_id",
    "display_name",
    "description",
    "role",
    "theme",
    "cluster",
    "groups",
)
DETAIL_FIELDS = SUMMARY_FIELDS + ("version", "instructions", "source_path")


def hierarchy_label(value: str) -> str:
    return " ".join(
        part.capitalize() for part in value.replace("_", "-").split("-") if part
    )


def _summary(row: Mapping[str, Any]) -> dict[str, Any]:
    raw = record_json(row)
    result = {field: raw.get(field) for field in SUMMARY_FIELDS}
    result["groups"] = json_value(raw.get("groups"), [])
    return result


def serialize_hierarchy(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    ordered = sorted(
        (_summary(row) for row in rows),
        key=lambda row: (
            (row["role"] or "").lower(),
            (row["theme"] or "").lower(),
            (row["cluster"] or "").lower(),
            row["display_name"].lower(),
            row["skill_id"],
        ),
    )
    roles: list[dict[str, Any]] = []
    for item in ordered:
        skill = {
            **item,
            **{key: item[key] or "ungrouped" for key in ("role", "theme", "cluster")},
        }
        role = next((item for item in roles if item["id"] == skill["role"]), None)
        if role is None:
            role = {
                "id": skill["role"],
                "label": hierarchy_label(skill["role"]),
                "count": 0,
                "themes": [],
            }
            roles.append(role)
        theme = next(
            (item for item in role["themes"] if item["id"] == skill["theme"]),
            None,
        )
        if theme is None:
            theme = {
                "id": skill["theme"],
                "label": hierarchy_label(skill["theme"]),
                "count": 0,
                "clusters": [],
            }
            role["themes"].append(theme)
        cluster = next(
            (item for item in theme["clusters"] if item["id"] == skill["cluster"]),
            None,
        )
        if cluster is None:
            cluster = {
                "id": skill["cluster"],
                "label": hierarchy_label(skill["cluster"]),
                "count": 0,
                "skills": [],
            }
            theme["clusters"].append(cluster)
        cluster["skills"].append(skill)
        cluster["count"] += 1
        theme["count"] += 1
        role["count"] += 1
    return {"total": len(ordered), "roles": roles, "items": ordered}


def serialize_skill(row: Mapping[str, Any]) -> dict[str, Any]:
    raw = record_json(row)
    result = {field: raw.get(field) for field in DETAIL_FIELDS}
    result["groups"] = json_value(raw.get("groups"), [])
    document = json_value(raw.get("metadata"), {})
    result.update(
        capabilities=document.get("capabilities", []),
        invocation=document.get("invocation", {}),
        metadata=document.get("metadata", {}),
    )
    source_path = result["source_path"]
    path = PurePosixPath(source_path) if isinstance(source_path, str) else None
    if (
        path is None
        or ABSOLUTE_PATH.match(source_path or "")
        or path.is_absolute()
        or ".." in path.parts
    ):
        result["source_path"] = "[redacted-path]"
    return result
