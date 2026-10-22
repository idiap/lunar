# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Optional typed projections of worker observations; raw frames remain authoritative."""

from datetime import datetime, timezone
from uuid import uuid5

from domain_packages.context import bind_context
from prism_runs.reasoning import project_source
from prism_runs.reasoning_repository import insert_entry
from .runs import encoded


def timestamp(value):
    return (
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        if isinstance(value, str)
        else datetime.now(timezone.utc)
    )


async def project_event(connection, context, run_id, event):
    payload = event["payload"]
    if not isinstance(payload, dict):
        return
    kind = event["kind"]
    identity = uuid5(run_id, "worker-projection:" + str(event["sequence"]))
    if (
        kind == "source"
        and {
            "resource_id",
            "source_local_identifier",
            "access_mode",
            "version_or_snapshot",
            "safe_locator",
            "content_digest",
        }
        <= payload.keys()
    ):
        await connection.execute(
            """INSERT INTO prism_run_consumed_sources
            (id,run_id,user_id,version_id,resource_id,source_local_identifier,access_point_id,operation_id,
             access_mode,version_or_snapshot,safe_locator,content_digest,observed_at,redacted_metadata)
            VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14::jsonb)""",
            identity,
            run_id,
            context.user_id,
            context.version_id,
            payload["resource_id"],
            payload["source_local_identifier"],
            payload.get("access_point_id"),
            payload.get("operation_id"),
            payload["access_mode"],
            payload["version_or_snapshot"],
            payload["safe_locator"],
            payload["content_digest"],
            timestamp(payload.get("observed_at")),
            encoded(payload.get("metadata", {})),
        )
    elif (
        kind == "input"
        and {"input_key", "kind", "safe_locator", "content_digest"} <= payload.keys()
    ):
        await connection.execute(
            """INSERT INTO prism_run_input_entities
            (id,run_id,user_id,version_id,input_key,kind,safe_locator,content_digest,observed_at,redacted_metadata)
            VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10::jsonb)""",
            identity,
            run_id,
            context.user_id,
            context.version_id,
            payload["input_key"],
            payload["kind"],
            payload["safe_locator"],
            payload["content_digest"],
            timestamp(payload.get("observed_at")),
            encoded(payload.get("metadata", {})),
        )
    elif kind == "stage" and {"stage_id", "component_id", "status"} <= payload.keys():
        await connection.execute(
            """UPDATE prism_run_events SET stage_id=$5,component_id=$6,status=$7,
            started_at=$8,finished_at=$9,safe_summary=$10,detail=detail || $11::jsonb
            WHERE id=$1 AND run_id=$2 AND user_id=$3 AND version_id=$4""",
            uuid5(run_id, "worker-event:" + str(event["sequence"])),
            run_id,
            context.user_id,
            context.version_id,
            payload["stage_id"],
            payload["component_id"],
            payload["status"],
            timestamp(payload.get("started_at")),
            timestamp(payload["finished_at"]) if payload.get("finished_at") else None,
            payload.get("safe_summary"),
            encoded(payload.get("detail", {})),
        )
    elif kind == "reasoning" and {"stage", "status"} <= payload.keys():
        source = project_source(
            stage=payload["stage"],
            status=payload["status"],
            result=payload.get("result"),
            evidence_references=payload.get("evidence_references", []),
            model_call=payload.get("model_call"),
            reasoning_step=payload.get("reasoning_step"),
        )
        with bind_context(context):
            entry = await insert_entry(
                connection,
                run_id=run_id,
                source_event_key=payload.get("source_event_key")
                or "worker:" + str(event["sequence"]),
                event_kind=payload.get("event_kind", "stage"),
                observed_at=timestamp(payload.get("observed_at")),
                source=source,
            )
            return entry
