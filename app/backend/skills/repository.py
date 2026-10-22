# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""PostgreSQL access for the selected imported skill catalog."""

from __future__ import annotations

from typing import Any

import asyncpg
from domain_packages.context import require_context

SUMMARY_COLUMNS = "skill_id, display_name, description, role, theme, cluster, groups"
DETAIL_COLUMNS = (
    "id, " + SUMMARY_COLUMNS + ", version, instructions, source_path, metadata"
)


async def list_skills(
    connection: asyncpg.Connection,
    *,
    query: str,
) -> list[Any]:
    context = require_context()
    pattern = f"%{query}%"
    return list(
        await connection.fetch(
            f"""
            SELECT {SUMMARY_COLUMNS}
            FROM skills
            WHERE version_id=$3 AND user_id=$4 AND ($1 = '' OR skill_id ILIKE $2 OR display_name ILIKE $2
                OR description ILIKE $2 OR role ILIKE $2 OR theme ILIKE $2
                OR cluster ILIKE $2)
            ORDER BY lower(role), role,
                lower(theme), theme, lower(cluster), cluster,
                lower(display_name), display_name, skill_id
            """,
            query,
            pattern,
            context.version_id,
            context.user_id,
        )
    )


async def get_skill(connection: asyncpg.Connection, skill_id: str) -> Any | None:
    context = require_context()
    return await connection.fetchrow(
        f"SELECT {DETAIL_COLUMNS} FROM skills WHERE skill_id = $1 AND version_id=$2 AND user_id=$3",
        skill_id,
        context.version_id,
        context.user_id,
    )
