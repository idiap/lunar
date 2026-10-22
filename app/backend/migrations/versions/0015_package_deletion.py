# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Persist in-progress package deletion across browser and backend restarts."""

from alembic import op

revision = "0015_package_deletion"
down_revision = "0014_package_exports"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "ALTER TABLE package_versions ADD COLUMN deletion_started_at TIMESTAMPTZ"
    )


def downgrade():
    op.execute("ALTER TABLE package_versions DROP COLUMN deletion_started_at")
