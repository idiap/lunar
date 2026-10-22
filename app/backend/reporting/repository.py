# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Transactional PostgreSQL access for generated reports."""

from __future__ import annotations

import uuid
from typing import Any

import asyncpg
from domain_packages.context import require_context


async def template_for_user(
    connection: asyncpg.Connection, template_id: uuid.UUID, user_id: uuid.UUID
) -> Any | None:
    require_context(user_id)
    return await connection.fetchrow(
        "SELECT id, user_id, name, content, updated_at FROM templates WHERE id=$1 AND user_id=$2 FOR SHARE",
        template_id,
        user_id,
    )


async def output_for_binding(
    connection: asyncpg.Connection,
    output_id: uuid.UUID,
    user_id: uuid.UUID,
) -> Any | None:
    context = require_context(user_id)
    return await connection.fetchrow(
        """
        SELECT o.id, o.run_id, o.output_key, o.component_id, o.markdown,
               o.structured_value, o.media_type, o.content_digest,
               o.provenance_entity_id, r.workflow_id, r.state, r.created_at,
               (SELECT COUNT(*) FROM prism_run_provenance_exports p WHERE p.run_id=r.id) AS provenance_count
        FROM prism_run_outputs o
        JOIN prism_runs r ON r.id=o.run_id
        WHERE o.id=$1 AND r.user_id=$2 AND r.version_id=$3 AND o.version_id=r.version_id AND o.user_id=r.user_id
        FOR SHARE OF o, r
        """,
        output_id,
        user_id,
        context.version_id,
    )


async def available_outputs(
    connection: asyncpg.Connection, user_id: uuid.UUID, output_keys: list[str]
) -> list[Any]:
    context = require_context(user_id)
    if not output_keys:
        return []
    return list(
        await connection.fetch(
            """
        SELECT o.id, o.run_id, o.output_key, o.content_digest, r.workflow_id, r.created_at
        FROM prism_run_outputs o JOIN prism_runs r ON r.id=o.run_id
        WHERE r.user_id=$1 AND r.version_id=$3 AND o.version_id=r.version_id AND o.user_id=r.user_id AND r.state='completed' AND o.output_key=ANY($2::text[])
          AND (SELECT COUNT(*) FROM prism_run_provenance_exports p WHERE p.run_id=r.id)=2
        ORDER BY r.created_at DESC, o.id
        """,
            user_id,
            output_keys,
            context.version_id,
        )
    )


async def report_lineage(
    connection: asyncpg.Connection, report_id: uuid.UUID, user_id: uuid.UUID
) -> Any | None:
    context = require_context(user_id)
    return await connection.fetchrow(
        """
        SELECT r.id, r.version_id,r.imported,r.generation_type, r.template_id, r.template_content_digest,
               r.generation_status, r.generated_at, r.provenance_data, t.name AS template_name
        FROM reports r LEFT JOIN templates t ON t.id=r.template_id
        WHERE r.id=$1 AND r.user_id=$2 AND r.version_id=$3
        """,
        report_id,
        user_id,
        context.version_id,
    )


async def report_export(
    connection: asyncpg.Connection, report_id: uuid.UUID, output_format: str
) -> Any | None:
    context = require_context()
    return await connection.fetchrow(
        """
        SELECT format, media_type, document, wrapper_digest, generated_at
        FROM report_provenance_exports WHERE report_id=$1 AND format=$2 AND user_id=$3 AND version_id=$4
        """,
        report_id,
        output_format,
        context.user_id,
        context.version_id,
    )


async def report_sections(
    connection: asyncpg.Connection, report_id: uuid.UUID
) -> list[Any]:
    context = require_context()
    return list(
        await connection.fetch(
            """
        SELECT s.id, s.section_id, s.ordinal, s.placeholder_name, s.run_output_id,
               s.content_digest, s.provenance_entity_id, o.run_id, o.output_key,
               o.content_digest AS output_digest, r.workflow_id
        FROM report_sections s
        LEFT JOIN prism_run_outputs o ON o.id=s.run_output_id AND o.user_id=s.user_id AND o.version_id=s.version_id
        LEFT JOIN prism_runs r ON r.id=o.run_id AND r.user_id=s.user_id AND r.version_id=s.version_id
        WHERE s.report_id=$1 AND s.user_id=$2 AND s.version_id=$3 ORDER BY s.ordinal, s.id
        """,
            report_id,
            context.user_id,
            context.version_id,
        )
    )
