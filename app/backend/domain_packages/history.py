# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Project original run observations and bind imported artifacts to package files."""

from datetime import datetime
import json
from uuid import uuid4

from .format.contract import _json


def timestamp(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


async def import_run_history(connection, context, run_id, facts, archive, files):
    owner, version = context.user_id, context.version_id
    await connection.execute(
        """UPDATE prism_runs SET created_at=COALESCE($4,created_at),started_at=$5,finished_at=$6,
        terminal_result_digest=$7 WHERE id=$1 AND user_id=$2 AND version_id=$3""",
        run_id,
        owner,
        version,
        timestamp(facts.get("created_at")),
        timestamp(facts.get("started_at")),
        timestamp(facts.get("finished_at")),
        facts.get("terminal_result_digest"),
    )
    projections = {
        "planned_sources": (
            "prism_run_planned_sources",
            ("resource_id", "source_local_identifier", "required", "binding_metadata"),
        ),
        "consumed_sources": (
            "prism_run_consumed_sources",
            (
                "resource_id",
                "source_local_identifier",
                "access_point_id",
                "operation_id",
                "access_mode",
                "version_or_snapshot",
                "safe_locator",
                "content_digest",
                "observed_at",
                "redacted_metadata",
            ),
        ),
        "input_entities": (
            "prism_run_input_entities",
            (
                "input_key",
                "kind",
                "safe_locator",
                "content_digest",
                "observed_at",
                "redacted_metadata",
            ),
        ),
        "events": (
            "prism_run_events",
            (
                "stage_id",
                "component_id",
                "status",
                "started_at",
                "finished_at",
                "safe_summary",
                "detail",
            ),
        ),
        "prism_reasoning_entries": (
            "prism_reasoning_entries",
            (
                "sequence",
                "source_event_key",
                "event_kind",
                "observed_at",
                "source",
                "source_digest",
                "presentation",
            ),
        ),
    }
    json_fields = {
        "binding_metadata",
        "redacted_metadata",
        "detail",
        "source",
        "presentation",
    }
    for key, (table, columns) in projections.items():
        for record in facts.get(key, []):
            if not isinstance(record, dict) or not set(columns) <= record.keys():
                continue
            values = []
            for column in columns:
                value = record[column]
                if column in json_fields:
                    if column == "presentation" and value.get("status") == "pending":
                        value = {
                            "status": "unavailable",
                            "unavailable_reason": "interrupted",
                            "icon_id": value.get("icon_id", "information"),
                        }
                    value = json.dumps(value, ensure_ascii=False, allow_nan=False)
                elif column.endswith("_at"):
                    value = timestamp(value)
                values.append(value)
            params = ",".join(
                "$" + str(index) + ("::jsonb" if column in json_fields else "")
                for index, column in enumerate(columns, 5)
            )
            await connection.execute(
                f"INSERT INTO {table}(id,run_id,user_id,version_id,{','.join(columns)}) VALUES($1,$2,$3,$4,{params})",
                uuid4(),
                run_id,
                owner,
                version,
                *values,
            )
    inventory = {row["path"]: row for row in archive.manifest["files"]}
    for artifact in facts.get("artifacts", []):
        if not isinstance(artifact, dict) or artifact.get("file") not in files:
            continue
        file = inventory[artifact["file"]]
        original = artifact.get("source_metadata", {})
        await connection.execute(
            """INSERT INTO prism_run_artifacts
            (id,run_id,user_id,version_id,artifact_key,safe_locator,media_type,content_digest,provenance_entity_id)
            VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9)""",
            uuid4(),
            run_id,
            owner,
            version,
            original.get("artifact_key", artifact["file"]),
            "package:" + str(files[artifact["file"]]),
            file["media_type"],
            "sha256:" + file["sha256"],
            original.get("provenance_entity_id", artifact.get("id", artifact["file"])),
        )
    provenance = {
        item["file"]: item
        for report in archive.documents["reports"]
        for item in report["provenance"]
    }
    seen = set()
    for receipt in facts.get("provenance_receipts", []):
        item = provenance.get(receipt.get("file"))
        if item is None or item["format"] in seen:
            continue
        seen.add(item["format"])
        await connection.execute(
            """INSERT INTO prism_run_provenance_exports
            (id,run_id,user_id,version_id,format,media_type,document,wrapper_digest,generated_at)
            VALUES($1,$2,$3,$4,$5,$6,$7::jsonb,$8,COALESCE($9,NOW()))""",
            uuid4(),
            run_id,
            owner,
            version,
            {"PROV-JSON": "prov-json", "JSON-LD": "json-ld"}[item["format"]],
            inventory[item["file"]]["media_type"],
            json.dumps(
                _json((archive.root / item["file"]).read_bytes()), ensure_ascii=False
            ),
            receipt.get("original_wrapper_digest", "sha256:" + item["sha256"]),
            timestamp(receipt.get("generated_at")),
        )
