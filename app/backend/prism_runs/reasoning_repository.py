# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Transactional live entries; caller owns the connection, never the executor thread."""

from __future__ import annotations

import uuid
from domain_packages.context import require_context
from datetime import datetime

from prism_runs.reasoning import Presentation, PublicSource, source_digest
from prism_runs.serialization import serialize_reasoning

CHANNEL = "prism_reasoning"


async def insert_entry(
    connection,
    *,
    run_id: uuid.UUID,
    source_event_key: str,
    event_kind: str,
    observed_at: datetime,
    source: PublicSource,
):
    context = require_context()
    async with connection.transaction():
        if not await connection.fetchval(
            "SELECT id FROM prism_runs WHERE id=$1 AND user_id=$2 AND version_id=$3 FOR UPDATE",
            run_id,
            context.user_id,
            context.version_id,
        ):
            return None
        existing = await connection.fetchrow(
            "SELECT * FROM prism_reasoning_entries WHERE run_id=$1 AND source_event_key=$2",
            run_id,
            source_event_key,
        )
        if existing:
            return serialize_reasoning(existing)
        sequence = await connection.fetchval(
            "SELECT COALESCE(MAX(sequence),0)+1 FROM prism_reasoning_entries WHERE run_id=$1",
            run_id,
        )
        row = await connection.fetchrow(
            """
            INSERT INTO prism_reasoning_entries
                (id,run_id,sequence,source_event_key,event_kind,observed_at,source,source_digest,presentation,user_id,version_id)
            VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb,$8,$9::jsonb,$10,$11) RETURNING *
        """,
            uuid.uuid4(),
            run_id,
            sequence,
            source_event_key,
            event_kind,
            observed_at,
            source.model_dump_json(),
            source_digest(source),
            Presentation().model_dump_json(),
            context.user_id,
            context.version_id,
        )
        return serialize_reasoning(row)


async def read_entries(connection, run_id):
    context = require_context()
    return [
        serialize_reasoning(row)
        for row in await connection.fetch(
            "SELECT * FROM prism_reasoning_entries WHERE run_id=$1 AND user_id=$2 AND version_id=$3 ORDER BY sequence",
            run_id,
            context.user_id,
            context.version_id,
        )
    ]


async def pending_entry(connection, entry_id):
    context = require_context()
    row = await connection.fetchrow(
        "SELECT * FROM prism_reasoning_entries WHERE id=$1 AND user_id=$2 AND version_id=$3 AND presentation->>'status'='pending'",
        uuid.UUID(str(entry_id)),
        context.user_id,
        context.version_id,
    )
    return serialize_reasoning(row) if row else None


async def settle_presentation(connection, entry_id, presentation: Presentation):
    context = require_context()
    if presentation.status == "pending":
        raise ValueError("settlement must be final")
    async with connection.transaction():
        return (
            await connection.fetchval(
                """
            UPDATE prism_reasoning_entries SET presentation=$2::jsonb
            WHERE id=$1 AND user_id=$3 AND version_id=$4 AND presentation->>'status'='pending' RETURNING id
        """,
                uuid.UUID(str(entry_id)),
                presentation.model_dump_json(),
                context.user_id,
                context.version_id,
            )
            is not None
        )


async def recover_presentations(connection):
    async with connection.transaction():
        return await connection.execute(
            """
            UPDATE prism_reasoning_entries SET presentation=$1::jsonb
            WHERE presentation->>'status'='pending'
        """,
            Presentation(
                status="unavailable", unavailable_reason="interrupted"
            ).model_dump_json(),
        )
