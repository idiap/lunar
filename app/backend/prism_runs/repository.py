# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Run inspection and deletion confined to the authenticated package version."""

from domain_packages.context import require_context
from modules.common import json_value

RUN_COLUMNS = """id,version_id,imported,workflow_id,operation,mode,state,safe_input_manifest,
accepted_plan_digest,artifact_root,error_summary,created_at,started_at,finished_at,
terminal_result_digest,ai_model_id,ai_model_snapshot"""


async def list_runs(connection, *, user_id, workflow_id, page, page_size):
    context = require_context(user_id)
    predicate = "user_id=$1 AND version_id=$2 AND ($3::text IS NULL OR workflow_id=$3)"
    total = await connection.fetchval(
        "SELECT COUNT(*) FROM prism_runs WHERE " + predicate,
        user_id,
        context.version_id,
        workflow_id,
    )
    rows = await connection.fetch(
        f"SELECT {RUN_COLUMNS} FROM prism_runs WHERE {predicate} ORDER BY created_at DESC,id DESC LIMIT $4 OFFSET $5",
        user_id,
        context.version_id,
        workflow_id,
        page_size,
        (page - 1) * page_size,
    )
    return list(rows), int(total)


async def get_run(connection, *, run_id, user_id):
    context = require_context(user_id)
    row = await connection.fetchrow(
        f"SELECT {RUN_COLUMNS} FROM prism_runs WHERE id=$1 AND user_id=$2 AND version_id=$3",
        run_id,
        user_id,
        context.version_id,
    )
    if row is None or not row["imported"]:
        return row
    original_id = await connection.fetchval(
        "SELECT source_id FROM package_import_mappings WHERE local_id=$1 AND user_id=$2 AND version_id=$3 AND source_collection='runs'",
        run_id,
        user_id,
        context.version_id,
    )
    document = await connection.fetchval(
        """SELECT document FROM package_resources
        WHERE user_id=$1 AND version_id=$2 AND collection='reports'
        AND document->'runs' @> jsonb_build_array(jsonb_build_object('id',$3::text)) LIMIT 1""",
        user_id,
        context.version_id,
        original_id,
    )
    facts = next(
        (
            item["facts"]
            for item in json_value(document, {}).get("runs", [])
            if item["id"] == original_id
        ),
        {},
    )
    return {**dict(row), "original_facts": facts}


async def get_artifact(connection, *, run_id, artifact_id, user_id):
    context = require_context(user_id)
    return await connection.fetchrow(
        """SELECT artifacts.*,runs.workflow_id,runs.artifact_root,runs.imported
        FROM prism_run_artifacts artifacts JOIN prism_runs runs ON runs.id=artifacts.run_id
        AND runs.user_id=artifacts.user_id AND runs.version_id=artifacts.version_id
        WHERE artifacts.id=$1 AND artifacts.run_id=$2 AND runs.user_id=$3 AND runs.version_id=$4""",
        artifact_id,
        run_id,
        user_id,
        context.version_id,
    )


async def delete_run(connection, *, run_id, user_id):
    context = require_context(user_id)
    result = await connection.execute(
        "DELETE FROM prism_runs WHERE id=$1 AND user_id=$2 AND version_id=$3 AND state IN ('completed','failed','cancelled')",
        run_id,
        user_id,
        context.version_id,
    )
    return result == "DELETE 1"


async def run_relations(connection, run_id):
    context = require_context()
    collections = {
        "planned_sources": ("prism_run_planned_sources", "resource_id,id"),
        "consumed_sources": ("prism_run_consumed_sources", "observed_at,id"),
        "input_entities": ("prism_run_input_entities", "observed_at,id"),
        "events": ("prism_run_events", "started_at,id"),
        "artifacts": ("prism_run_artifacts", "artifact_key,id"),
        "outputs": ("prism_run_outputs", "output_key"),
    }
    result = {}
    for key, (table, order) in collections.items():
        rows = await connection.fetch(
            f"SELECT * FROM {table} WHERE run_id=$1 AND user_id=$2 AND version_id=$3 ORDER BY {order}",
            run_id,
            context.user_id,
            context.version_id,
        )
        result[key] = [
            {
                name: value
                for name, value in dict(row).items()
                if name not in {"user_id", "version_id", "run_id"}
            }
            for row in rows
        ]
    sources = await connection.fetch(
        "SELECT resource_id,name FROM data_sources WHERE user_id=$1 AND version_id=$2",
        context.user_id,
        context.version_id,
    )
    names = {row["resource_id"]: row["name"] for row in sources}
    for row in result["consumed_sources"]:
        row["name"] = names.get(row["resource_id"], row["resource_id"])
    return result
