# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Create persistent Prism run, observation, output, and provenance tables."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008_create_prism_runs"
down_revision: str | None = "0007_create_data_sources"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def timestamp(name: str, *, nullable: bool = True, default: bool = False) -> sa.Column:
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        nullable=nullable,
        server_default=sa.text("NOW()") if default else None,
    )


def upgrade() -> None:
    op.create_table(
        "prism_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("workflow_id", sa.Text(), nullable=False),
        sa.Column("operation", sa.Text(), nullable=False),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("safe_input_manifest", postgresql.JSONB(), nullable=False),
        sa.Column("accepted_plan_digest", sa.String(length=71), nullable=False),
        sa.Column("artifact_root", sa.Text(), nullable=False),
        sa.Column("error_summary", sa.Text()),
        timestamp("created_at", nullable=False, default=True),
        timestamp("started_at"),
        timestamp("finished_at"),
        sa.Column("terminal_result_digest", sa.String(length=71)),
        sa.CheckConstraint(
            "state IN ('queued', 'running', 'completed', 'failed', 'cancelled')",
            name="ck_prism_runs_state",
        ),
    )
    op.create_index(
        "ix_prism_runs_user_created_at", "prism_runs", ["user_id", "created_at"]
    )
    op.create_index(
        "ix_prism_runs_workflow_created_at", "prism_runs", ["workflow_id", "created_at"]
    )

    op.create_table(
        "prism_run_planned_sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("prism_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "resource_id",
            sa.Text(),
            sa.ForeignKey("data_sources.resource_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("source_local_identifier", sa.Text()),
        sa.Column("required", sa.Boolean(), nullable=False),
        sa.Column(
            "binding_metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )

    op.create_table(
        "prism_run_consumed_sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("prism_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "resource_id",
            sa.Text(),
            sa.ForeignKey("data_sources.resource_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("source_local_identifier", sa.Text(), nullable=False),
        sa.Column("access_point_id", sa.Text()),
        sa.Column("operation_id", sa.Text()),
        sa.Column("access_mode", sa.Text(), nullable=False),
        sa.Column("version_or_snapshot", sa.Text(), nullable=False),
        sa.Column("safe_locator", sa.Text(), nullable=False),
        sa.Column("content_digest", sa.String(length=71), nullable=False),
        timestamp("observed_at", nullable=False, default=True),
        sa.Column(
            "redacted_metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.create_index(
        "ix_prism_consumed_source_run",
        "prism_run_consumed_sources",
        ["resource_id", "run_id"],
    )

    op.create_table(
        "prism_run_input_entities",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("prism_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("input_key", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("safe_locator", sa.Text(), nullable=False),
        sa.Column("content_digest", sa.String(length=71), nullable=False),
        timestamp("observed_at", nullable=False, default=True),
        sa.Column(
            "redacted_metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )

    op.create_table(
        "prism_run_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("prism_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("stage_id", sa.Text(), nullable=False),
        sa.Column("component_id", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        timestamp("started_at", nullable=False),
        timestamp("finished_at"),
        sa.Column("safe_summary", sa.Text()),
    )

    op.create_table(
        "prism_run_artifacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("prism_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("artifact_key", sa.Text(), nullable=False),
        sa.Column("safe_locator", sa.Text(), nullable=False),
        sa.Column("media_type", sa.Text(), nullable=False),
        sa.Column("content_digest", sa.String(length=71), nullable=False),
        sa.Column("provenance_entity_id", sa.Text(), nullable=False),
    )

    op.create_table(
        "prism_run_outputs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("prism_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("output_key", sa.Text(), nullable=False),
        sa.Column("component_id", sa.Text(), nullable=False),
        sa.Column("markdown", sa.Text()),
        sa.Column("structured_value", postgresql.JSONB()),
        sa.Column("media_type", sa.Text(), nullable=False),
        sa.Column("content_digest", sa.String(length=71), nullable=False),
        sa.Column("provenance_entity_id", sa.Text(), nullable=False),
        timestamp("created_at", nullable=False, default=True),
        sa.UniqueConstraint("run_id", "output_key", name="uq_prism_run_outputs_key"),
        sa.CheckConstraint(
            "markdown IS NOT NULL OR structured_value IS NOT NULL",
            name="ck_prism_run_outputs_content",
        ),
    )
    op.create_index(
        "ix_prism_run_outputs_output_key", "prism_run_outputs", ["output_key"]
    )

    op.create_table(
        "prism_run_provenance_exports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("prism_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("format", sa.Text(), nullable=False),
        sa.Column("media_type", sa.Text(), nullable=False),
        sa.Column("document", postgresql.JSONB(), nullable=False),
        sa.Column("wrapper_digest", sa.String(length=71), nullable=False),
        timestamp("generated_at", nullable=False, default=True),
        sa.UniqueConstraint("run_id", "format", name="uq_prism_run_provenance_format"),
        sa.CheckConstraint(
            "format IN ('prov-json', 'json-ld')", name="ck_prism_provenance_format"
        ),
    )


def downgrade() -> None:
    for table in (
        "prism_run_provenance_exports",
        "prism_run_outputs",
        "prism_run_artifacts",
        "prism_run_events",
        "prism_run_input_entities",
        "prism_run_consumed_sources",
        "prism_run_planned_sources",
        "prism_runs",
    ):
        op.drop_table(table)
