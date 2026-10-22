# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""PostgreSQL persistence for immutable provenance exports."""

from __future__ import annotations

import uuid
from typing import Any

import asyncpg
from domain_packages.context import require_context


async def get_export(
    connection: asyncpg.Connection,
    *,
    run_id: uuid.UUID,
    user_id: uuid.UUID,
    output_format: str,
) -> Any | None:
    context = require_context(user_id)
    return await connection.fetchrow(
        """
        SELECT e.format, e.media_type, e.document, e.wrapper_digest, e.generated_at
        FROM prism_run_provenance_exports e
        JOIN prism_runs r ON r.id = e.run_id
        WHERE e.run_id = $1 AND r.user_id = $2 AND e.format = $3 AND r.version_id=$4 AND e.version_id=r.version_id AND e.user_id=r.user_id
        """,
        run_id,
        user_id,
        output_format,
        context.version_id,
    )
