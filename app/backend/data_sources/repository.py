# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""PostgreSQL access for the selected imported data-source catalog."""

from __future__ import annotations

from typing import Any

import asyncpg
from domain_packages.context import require_context

SUMMARY_COLUMNS = """
resource_id, name, category, scope, canonical_uri, posture, claim_ceiling,
owner, refresh_trigger, verified_as_of, schema_version, catalog_digest,
aliases, modalities, descriptor, descriptor->'descriptor'->>'visibility' AS visibility
"""
DETAIL_COLUMNS = (
    "id, "
    + SUMMARY_COLUMNS
    + ", entities, identifiers, access_points, operations, candidate_operations, lineage"
)


async def list_sources(
    connection: asyncpg.Connection,
    *,
    query: str,
    page: int,
    page_size: int,
) -> tuple[list[Any], int]:
    context = require_context()
    pattern = f"%{query}%"
    predicate = """
        version_id=$3 AND user_id=$4 AND ($1 = '' OR resource_id ILIKE $2 OR name ILIKE $2 OR category ILIKE $2
        OR scope ILIKE $2 OR aliases::text ILIKE $2 OR modalities::text ILIKE $2)
    """
    total = await connection.fetchval(
        f"SELECT COUNT(*) FROM data_sources WHERE {predicate}",
        query,
        pattern,
        context.version_id,
        context.user_id,
    )
    rows = await connection.fetch(
        f"""
        SELECT {SUMMARY_COLUMNS}
        FROM data_sources
        WHERE {predicate}
        ORDER BY lower(name), resource_id
        LIMIT $5 OFFSET $6
        """,
        query,
        pattern,
        context.version_id,
        context.user_id,
        page_size,
        (page - 1) * page_size,
    )
    return list(rows), int(total or 0)


async def get_source(connection: asyncpg.Connection, resource_id: str) -> Any | None:
    context = require_context()
    return await connection.fetchrow(
        f"SELECT {DETAIL_COLUMNS} FROM data_sources WHERE resource_id = $1 AND version_id=$2 AND user_id=$3",
        resource_id,
        context.version_id,
        context.user_id,
    )
