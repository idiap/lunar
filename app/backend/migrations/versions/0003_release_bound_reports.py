# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Bind published reports to exact quality-release receipts."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_release_bound_reports"
down_revision: str | None = "0002_users_and_report_ownership"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "reports", sa.Column("artifact_digest", sa.String(length=71), nullable=True)
    )
    op.add_column(
        "reports", sa.Column("release_receipt", postgresql.JSONB(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("reports", "release_receipt")
    op.drop_column("reports", "artifact_digest")
