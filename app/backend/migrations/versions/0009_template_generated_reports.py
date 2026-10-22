# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Add template-generated report lineage and W3C provenance tables."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009_template_generated_reports"
down_revision: str | None = "0008_create_prism_runs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Templates predate Alembic ownership in this app; make the FK target available
    # on both fresh databases and databases initialized by schema.py.
    op.execute("""
        CREATE TABLE IF NOT EXISTS templates (
            id UUID PRIMARY KEY,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            content TEXT NOT NULL,
            agent UUID,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_templates_user_id ON templates(user_id)")
    op.add_column("reports", sa.Column("template_id", postgresql.UUID(as_uuid=True)))
    op.add_column("reports", sa.Column("template_content_digest", sa.String(length=71)))
    op.add_column("reports", sa.Column("generation_status", sa.Text()))
    op.add_column("reports", sa.Column("generation_type", sa.Text()))
    op.add_column("reports", sa.Column("generated_at", sa.DateTime(timezone=True)))
    op.create_foreign_key(
        "fk_reports_template_id",
        "reports",
        "templates",
        ["template_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint(
        "ck_reports_generation_status",
        "reports",
        "generation_status IS NULL OR generation_status IN ('completed', 'failed')",
    )
    op.create_check_constraint(
        "ck_reports_generation_type",
        "reports",
        "generation_type IS NULL OR generation_type = 'template'",
    )

    op.create_table(
        "report_sections",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("section_id", sa.Text(), nullable=False),
        sa.Column(
            "report_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("reports.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("placeholder_name", sa.Text(), nullable=False),
        sa.Column(
            "run_output_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("prism_run_outputs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("rendered_markdown", sa.Text(), nullable=False),
        sa.Column("content_digest", sa.String(length=71), nullable=False),
        sa.Column("provenance_entity_id", sa.Text(), nullable=False),
        sa.UniqueConstraint(
            "report_id", "section_id", name="uq_report_sections_stable_id"
        ),
        sa.UniqueConstraint("report_id", "ordinal", name="uq_report_sections_ordinal"),
        sa.CheckConstraint("ordinal >= 0", name="ck_report_sections_ordinal"),
    )
    op.create_index("ix_report_sections_output", "report_sections", ["run_output_id"])
    op.create_table(
        "report_provenance_exports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "report_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("reports.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("format", sa.Text(), nullable=False),
        sa.Column("media_type", sa.Text(), nullable=False),
        sa.Column("document", postgresql.JSONB(), nullable=False),
        sa.Column("wrapper_digest", sa.String(length=71), nullable=False),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.UniqueConstraint("report_id", "format", name="uq_report_provenance_format"),
        sa.CheckConstraint(
            "format IN ('prov-json', 'json-ld')", name="ck_report_provenance_format"
        ),
    )


def downgrade() -> None:
    op.drop_table("report_provenance_exports")
    op.drop_index("ix_report_sections_output", table_name="report_sections")
    op.drop_table("report_sections")
    op.drop_constraint("ck_reports_generation_type", "reports", type_="check")
    op.drop_constraint("ck_reports_generation_status", "reports", type_="check")
    op.drop_constraint("fk_reports_template_id", "reports", type_="foreignkey")
    for column in (
        "generated_at",
        "generation_type",
        "generation_status",
        "template_content_digest",
        "template_id",
    ):
        op.drop_column("reports", column)
