# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Create the global canonical skill catalog."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_create_skills"
down_revision: str | None = "0010_prism_model_trace"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "skills",
        sa.Column("skill_id", sa.Text(), primary_key=True),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("version", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("instructions", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("theme", sa.Text(), nullable=False),
        sa.Column("cluster", sa.Text(), nullable=False),
        sa.Column("source_path", sa.Text(), nullable=False),
        sa.Column("catalog_digest", sa.String(length=71), nullable=False),
        sa.CheckConstraint(
            "role IN ('readers', 'reasoners', 'writers')",
            name="ck_skills_supported_role",
        ),
        sa.CheckConstraint(
            "length(btrim(skill_id)) > 0 AND length(btrim(theme)) > 0 "
            "AND length(btrim(cluster)) > 0",
            name="ck_skills_nonempty_hierarchy",
        ),
    )
    op.execute(
        "CREATE INDEX ix_skills_hierarchy_name "
        "ON skills (role, lower(theme), lower(cluster), lower(display_name), skill_id)"
    )


def downgrade() -> None:
    op.drop_table("skills")
