# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Record completed owned export snapshots without retaining download archives."""

from alembic import op

revision = "0014_package_exports"
down_revision = "0013_package_ownership"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""CREATE TABLE package_exports (
        id UUID PRIMARY KEY, user_id UUID NOT NULL, version_id UUID NOT NULL,
        archive_digest TEXT NOT NULL CHECK (archive_digest ~ '^[0-9a-f]{64}$'),
        source_archive_digest TEXT NOT NULL, snapshot_at TIMESTAMPTZ NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        FOREIGN KEY(version_id,user_id) REFERENCES package_versions(id,user_id) ON DELETE CASCADE
    )""")


def downgrade():
    op.execute("DROP TABLE package_exports")
