# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Create the global data-source catalog."""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007_create_data_sources"
down_revision: str | None = "0006_persist_chat_interrupts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

POSTURES = "'descriptor_only', 'intent_only', 'fixture_ready', 'live_ready', 'blocked'"
JSON_COLUMNS = (
    "aliases",
    "modalities",
    "entities",
    "identifiers",
    "access_points",
    "operations",
    "candidate_operations",
    "lineage",
)


def upgrade() -> None:
    columns: list[Any] = [
        sa.Column("resource_id", sa.Text(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("canonical_uri", sa.Text(), nullable=False),
        sa.Column("posture", sa.Text(), nullable=False),
        sa.Column("claim_ceiling", sa.Text(), nullable=False),
        sa.Column("owner", sa.Text(), nullable=False),
        sa.Column("refresh_trigger", sa.Text(), nullable=False),
        sa.Column("verified_as_of", sa.Text(), nullable=False),
        sa.Column("schema_version", sa.Text(), nullable=False),
        sa.Column("catalog_digest", sa.String(length=71), nullable=False),
    ]
    columns.extend(
        sa.Column(
            name,
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        )
        for name in JSON_COLUMNS
    )
    columns.append(sa.Column("descriptor", postgresql.JSONB(), nullable=False))
    columns.append(
        sa.CheckConstraint(
            f"posture IN ({POSTURES})",
            name="ck_data_sources_supported_posture",
        )
    )
    op.create_table("data_sources", *columns)

    op.execute(
        "CREATE INDEX ix_data_sources_lower_name_resource_id "
        "ON data_sources (lower(name), resource_id)"
    )
    for column in ("resource_id", "category", "scope"):
        op.execute(
            f"CREATE INDEX ix_data_sources_lower_{column} "
            f"ON data_sources (lower({column}))"
        )
    for column in ("aliases", "modalities"):
        op.create_index(
            f"ix_data_sources_{column}_gin",
            "data_sources",
            [column],
            postgresql_using="gin",
        )


def downgrade() -> None:
    op.drop_table("data_sources")
