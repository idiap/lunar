# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Add selected-model identity and safe native PRISM event detail."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010_prism_model_trace"
down_revision: str | None = "0009_template_generated_reports"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "prism_runs",
        sa.Column("ai_model_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "prism_runs",
        sa.Column("ai_model_snapshot", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "prism_run_events",
        sa.Column(
            "detail",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("prism_run_events", "detail")
    op.drop_column("prism_runs", "ai_model_snapshot")
    op.drop_column("prism_runs", "ai_model_id")
