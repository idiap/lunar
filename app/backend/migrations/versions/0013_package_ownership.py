# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Bind imported resources, runs and lineage to an authenticated package version."""

from alembic import op
import sqlalchemy as sa

revision = "0013_package_ownership"
down_revision = "0012_prism_reasoning_entries"
branch_labels = None
depends_on = None

RUN_CHILDREN = (
    "prism_run_planned_sources",
    "prism_run_consumed_sources",
    "prism_run_input_entities",
    "prism_run_events",
    "prism_run_artifacts",
    "prism_run_outputs",
    "prism_run_provenance_exports",
    "prism_reasoning_entries",
)
REPORT_CHILDREN = ("report_sections", "report_provenance_exports")


def upgrade():
    op.execute("""
    CREATE TABLE domain_packages (
        id UUID PRIMARY KEY, user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        package_key TEXT NOT NULL, display_name TEXT NOT NULL,
        next_version BIGINT NOT NULL DEFAULT 1 CHECK(next_version > 0),
        UNIQUE(user_id, package_key), UNIQUE(id, user_id)
    );
    CREATE TABLE package_versions (
        id UUID PRIMARY KEY, package_id UUID NOT NULL, user_id UUID NOT NULL,
        version BIGINT NOT NULL CHECK(version > 0),
        status TEXT NOT NULL CHECK(status IN ('staging','ready','failed')),
        archive_digest TEXT NOT NULL CHECK(archive_digest ~ '^[0-9a-f]{64}$'),
        manifest JSONB NOT NULL,
        runtime_state TEXT NOT NULL DEFAULT 'unprepared'
            CHECK(runtime_state IN ('unprepared','preparing','ready','failed')),
        runtime_image TEXT, error TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(package_id, version), UNIQUE(id, user_id),
        FOREIGN KEY(package_id,user_id) REFERENCES domain_packages(id,user_id) ON DELETE CASCADE
    );
    CREATE TABLE package_resources (
        id UUID PRIMARY KEY, version_id UUID NOT NULL, user_id UUID NOT NULL,
        collection TEXT NOT NULL CHECK(collection IN ('repository','reports','skills','data-sources')),
        logical_id TEXT NOT NULL, document JSONB NOT NULL,
        UNIQUE(version_id,collection,logical_id), UNIQUE(id,version_id,user_id),
        FOREIGN KEY(version_id,user_id) REFERENCES package_versions(id,user_id) ON DELETE CASCADE
    );
    CREATE TABLE package_files (
        id UUID PRIMARY KEY, version_id UUID NOT NULL, user_id UUID NOT NULL,
        path TEXT NOT NULL, size BIGINT NOT NULL CHECK(size >= 0),
        sha256 TEXT NOT NULL CHECK(sha256 ~ '^[0-9a-f]{64}$'), media_type TEXT NOT NULL,
        storage_kind TEXT NOT NULL CHECK(storage_kind IN ('database','filesystem')),
        payload BYTEA,
        CHECK((storage_kind='database' AND payload IS NOT NULL AND octet_length(payload)=size)
           OR (storage_kind='filesystem' AND payload IS NULL)),
        UNIQUE(version_id,path), UNIQUE(id,version_id,user_id),
        FOREIGN KEY(version_id,user_id) REFERENCES package_versions(id,user_id) ON DELETE CASCADE
    );
    CREATE TABLE package_resource_files (
        resource_id UUID NOT NULL, file_id UUID NOT NULL,
        version_id UUID NOT NULL, user_id UUID NOT NULL,
        PRIMARY KEY(resource_id,file_id),
        FOREIGN KEY(resource_id,version_id,user_id) REFERENCES package_resources(id,version_id,user_id) ON DELETE CASCADE,
        FOREIGN KEY(file_id,version_id,user_id) REFERENCES package_files(id,version_id,user_id) ON DELETE CASCADE
    );
    CREATE TABLE package_resource_links (
        source_id UUID NOT NULL, target_id UUID NOT NULL,
        version_id UUID NOT NULL, user_id UUID NOT NULL,
        PRIMARY KEY(source_id,target_id),
        FOREIGN KEY(source_id,version_id,user_id) REFERENCES package_resources(id,version_id,user_id) ON DELETE CASCADE,
        FOREIGN KEY(target_id,version_id,user_id) REFERENCES package_resources(id,version_id,user_id) ON DELETE CASCADE
    );
    CREATE TABLE package_import_mappings (
        version_id UUID NOT NULL, user_id UUID NOT NULL,
        source_collection TEXT NOT NULL, source_id TEXT NOT NULL, local_id UUID NOT NULL,
        PRIMARY KEY(version_id,source_collection,source_id),
        FOREIGN KEY(version_id,user_id) REFERENCES package_versions(id,user_id) ON DELETE CASCADE
    );
    CREATE TABLE package_workflows (
        id UUID PRIMARY KEY, version_id UUID NOT NULL, user_id UUID NOT NULL,
        workflow_id TEXT NOT NULL, registration JSONB NOT NULL,
        UNIQUE(version_id,workflow_id),
        FOREIGN KEY(version_id,user_id) REFERENCES package_versions(id,user_id) ON DELETE CASCADE
    );
    CREATE TABLE package_planner_state (
        reference TEXT PRIMARY KEY, kind TEXT NOT NULL,
        version_id UUID NOT NULL, user_id UUID NOT NULL, payload JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), expires_at TIMESTAMPTZ,
        FOREIGN KEY(version_id,user_id) REFERENCES package_versions(id,user_id) ON DELETE CASCADE
    );
    """)
    # Fresh-install migration: no legacy account/catalog migration is supported.
    # Remove old unscoped edges before changing their referenced keys.
    inspector = sa.inspect(op.get_bind())
    for table in (*RUN_CHILDREN, *REPORT_CHILDREN):
        for fk in inspector.get_foreign_keys(table):
            if fk["referred_table"] in {
                "prism_runs",
                "reports",
                "prism_run_outputs",
                "data_sources",
            }:
                constraint_name = fk.get("name")
                if constraint_name is not None:
                    op.drop_constraint(constraint_name, table, type_="foreignkey")
    for table in ("skills", "data_sources"):
        constraint_name = inspector.get_pk_constraint(table).get("name")
        if constraint_name is not None:
            op.drop_constraint(constraint_name, table, type_="primary")
        op.execute(
            f"ALTER TABLE {table} ADD COLUMN id UUID NOT NULL DEFAULT gen_random_uuid(); ALTER TABLE {table} ADD PRIMARY KEY(id)"
        )
    for table in (
        "skills",
        "data_sources",
        "reports",
        "prism_runs",
        *RUN_CHILDREN,
        *REPORT_CHILDREN,
    ):
        if table not in {"reports", "prism_runs"}:
            op.execute(f"ALTER TABLE {table} ADD COLUMN user_id UUID NOT NULL")
        op.execute(f"ALTER TABLE {table} ADD COLUMN version_id UUID NOT NULL")
        op.create_foreign_key(
            f"fk_{table}_package_owner",
            table,
            "package_versions",
            ["version_id", "user_id"],
            ["id", "user_id"],
            ondelete="CASCADE",
        )
        op.create_unique_constraint(
            f"uq_{table}_context", table, ["id", "version_id", "user_id"]
        )
    op.create_unique_constraint(
        "uq_skills_version_logical", "skills", ["version_id", "skill_id"]
    )
    op.create_unique_constraint(
        "uq_sources_version_logical", "data_sources", ["version_id", "resource_id"]
    )
    for table in RUN_CHILDREN:
        op.create_foreign_key(
            f"fk_{table}_run_context",
            table,
            "prism_runs",
            ["run_id", "version_id", "user_id"],
            ["id", "version_id", "user_id"],
            ondelete="CASCADE",
        )
    for table in ("prism_run_planned_sources", "prism_run_consumed_sources"):
        op.create_foreign_key(
            f"fk_{table}_source_context",
            table,
            "data_sources",
            ["version_id", "resource_id"],
            ["version_id", "resource_id"],
            ondelete="RESTRICT",
        )
    for table in REPORT_CHILDREN:
        op.create_foreign_key(
            f"fk_{table}_report_context",
            table,
            "reports",
            ["report_id", "version_id", "user_id"],
            ["id", "version_id", "user_id"],
            ondelete="CASCADE",
        )
    op.create_foreign_key(
        "fk_report_sections_output_context",
        "report_sections",
        "prism_run_outputs",
        ["run_output_id", "version_id", "user_id"],
        ["id", "version_id", "user_id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_runs_workflow_context",
        "prism_runs",
        "package_workflows",
        ["version_id", "workflow_id"],
        ["version_id", "workflow_id"],
        ondelete="RESTRICT",
    )
    op.execute("""
    ALTER TABLE chats ADD COLUMN version_id UUID;
    ALTER TABLE chats ADD CONSTRAINT fk_chats_package_owner FOREIGN KEY(version_id,user_id) REFERENCES package_versions(id,user_id);
    ALTER TABLE skills DROP CONSTRAINT ck_skills_supported_role;
    ALTER TABLE skills DROP CONSTRAINT ck_skills_nonempty_hierarchy;
    ALTER TABLE skills ALTER COLUMN role DROP NOT NULL;
    ALTER TABLE skills ALTER COLUMN theme DROP NOT NULL;
    ALTER TABLE skills ALTER COLUMN cluster DROP NOT NULL;
    ALTER TABLE skills ADD COLUMN metadata JSONB NOT NULL DEFAULT '{}'::jsonb;
    ALTER TABLE skills ADD COLUMN groups JSONB NOT NULL DEFAULT '[]'::jsonb;
    ALTER TABLE reports ADD COLUMN logical_id TEXT;
    ALTER TABLE reports ADD COLUMN imported BOOLEAN NOT NULL DEFAULT FALSE;
    ALTER TABLE reports ADD CONSTRAINT uq_reports_version_logical UNIQUE(version_id,logical_id);
    ALTER TABLE prism_runs ADD COLUMN imported BOOLEAN NOT NULL DEFAULT FALSE;
    ALTER TABLE report_sections ALTER COLUMN run_output_id DROP NOT NULL;
    ALTER TABLE templates ADD CONSTRAINT uq_templates_owner UNIQUE(id,user_id);
    ALTER TABLE reports DROP CONSTRAINT fk_reports_template_id;
    ALTER TABLE reports ADD CONSTRAINT fk_reports_template_owner FOREIGN KEY(template_id,user_id)
        REFERENCES templates(id,user_id) ON DELETE SET NULL(template_id);
    CREATE TABLE report_revisions (
        report_id UUID NOT NULL, version_id UUID NOT NULL, user_id UUID NOT NULL,
        revision INTEGER NOT NULL CHECK(revision > 0), content TEXT NOT NULL,
        metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
        PRIMARY KEY(report_id,revision),
        FOREIGN KEY(report_id,version_id,user_id) REFERENCES reports(id,version_id,user_id) ON DELETE CASCADE
    );
    CREATE FUNCTION protect_package_context() RETURNS trigger AS $$
    BEGIN
        IF (NEW.user_id,NEW.version_id) IS DISTINCT FROM (OLD.user_id,OLD.version_id) THEN
            RAISE EXCEPTION 'package ownership and version binding are immutable';
        END IF;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """)
    op.execute("""
    CREATE FUNCTION protect_package_identity() RETURNS trigger AS $$
    BEGIN
        IF (NEW.id,NEW.user_id,NEW.package_key) IS DISTINCT FROM (OLD.id,OLD.user_id,OLD.package_key)
            OR NEW.next_version < OLD.next_version THEN
            RAISE EXCEPTION 'package identity and monotonic counter are immutable';
        END IF;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    CREATE TRIGGER package_identity_immutable BEFORE UPDATE ON domain_packages
        FOR EACH ROW EXECUTE FUNCTION protect_package_identity();
    CREATE FUNCTION protect_import_identity() RETURNS trigger AS $$
    BEGIN
        IF (NEW.id,NEW.user_id,NEW.package_id,NEW.version,NEW.archive_digest,NEW.manifest)
            IS DISTINCT FROM (OLD.id,OLD.user_id,OLD.package_id,OLD.version,OLD.archive_digest,OLD.manifest)
            OR (OLD.status IN ('ready','failed') AND NEW.status <> OLD.status) THEN
            RAISE EXCEPTION 'import identity and terminal publication state are immutable';
        END IF;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    CREATE TRIGGER import_identity_immutable BEFORE UPDATE ON package_versions
        FOR EACH ROW EXECUTE FUNCTION protect_import_identity();
    """)
    for table in (
        "skills",
        "data_sources",
        "reports",
        "prism_runs",
        "chats",
        *RUN_CHILDREN,
        *REPORT_CHILDREN,
        "package_resources",
        "package_files",
        "package_workflows",
        "package_planner_state",
        "report_revisions",
    ):
        op.execute(
            f"CREATE TRIGGER {table}_context_immutable BEFORE UPDATE ON {table} FOR EACH ROW EXECUTE FUNCTION protect_package_context()"
        )


def downgrade():
    # Removing tenant boundaries while retaining package data is not a safe downgrade.
    raise RuntimeError(
        "Package ownership migration requires restoring a matched pre-migration database backup to downgrade"
    )
