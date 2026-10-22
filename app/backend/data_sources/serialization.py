# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Safe serialization for catalog records."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from modules.common import json_value, record_json

SUMMARY_FIELDS = (
    "resource_id",
    "name",
    "category",
    "scope",
    "canonical_uri",
    "posture",
    "claim_ceiling",
    "owner",
    "refresh_trigger",
    "verified_as_of",
    "schema_version",
    "catalog_digest",
    "aliases",
    "modalities",
)
DETAIL_FIELDS = SUMMARY_FIELDS + (
    "entities",
    "identifiers",
    "access_points",
    "operations",
    "candidate_operations",
    "lineage",
    "descriptor",
)
JSON_FIELDS = {
    "aliases",
    "modalities",
    "entities",
    "identifiers",
    "access_points",
    "operations",
    "candidate_operations",
    "lineage",
    "descriptor",
}
ABSOLUTE_PATH = re.compile(r"^(?:/|file://|[A-Za-z]:[\\/])")


def source_selection(
    resource_id: str, document: dict[str, Any]
) -> dict[str, Any] | None:
    """Expose only the typed reference metadata needed by version-scoped pickers.

    This describes registered content, not a new byte-verification or execution.
    Preparation still validates payload digests and decodes the declared type.
    """
    if (
        not isinstance(document, dict)
        or not isinstance(resource_id, str)
        or not resource_id
    ):
        return None
    descriptor = document.get("descriptor", document)
    if not isinstance(descriptor, dict):
        return None
    version, digest = descriptor.get("package_version"), descriptor.get("digest")
    kind, schema = descriptor.get("content_kind"), descriptor.get("native_schema")
    if (
        not isinstance(version, str)
        or not version
        or not isinstance(digest, str)
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest)
        or kind not in {"json", "file", "directory"}
        or not isinstance(schema, dict)
    ):
        return None
    files = document.get("local_files", [])
    materialized = (
        isinstance(files, list)
        and len(files) == 1
        and isinstance(files[0], dict)
        and files[0].get("id") == "payload"
        and bool(files[0].get("file"))
    )
    if kind == "directory":
        materialized = isinstance(descriptor.get("tree"), dict) and bool(
            descriptor.get("payload_root")
        )
    return {
        "reference": {
            "source_id": resource_id,
            "package_version": version,
            "digest": digest,
        },
        "content_kind": kind,
        "native_schema": _safe_value(schema),
        "materialized": materialized,
    }


def _safe_value(value: Any) -> Any:
    if isinstance(value, str) and ABSOLUTE_PATH.match(value):
        return "[redacted-path]"
    if isinstance(value, list):
        return [_safe_value(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): _safe_value(item) for key, item in value.items()}
    return value


def serialize_source(row: Mapping[str, Any], *, detail: bool = False) -> dict[str, Any]:
    raw = record_json(row)
    result: dict[str, Any] = {}
    for field in DETAIL_FIELDS if detail else SUMMARY_FIELDS:
        value = (
            json_value(raw.get(field), {} if field == "descriptor" else [])
            if field in JSON_FIELDS
            else raw.get(field)
        )
        result[field] = _safe_value(value)
    document = json_value(raw.get("descriptor"), {})
    descriptor = document.get("descriptor", document)
    result["visibility"] = descriptor.get("visibility", raw.get("visibility"))
    resource_id = raw.get("resource_id")
    result["selection"] = (
        source_selection(resource_id, document)
        if isinstance(resource_id, str)
        else None
    )
    if detail:
        result["descriptor"] = _safe_value(descriptor)
        result["datasets"] = _safe_value(descriptor.get("datasets", []))
        result["local_files"] = document.get("local_files", [])
        result["remote_references"] = document.get("remote_references", [])
        result["workflows"] = []
    return result
