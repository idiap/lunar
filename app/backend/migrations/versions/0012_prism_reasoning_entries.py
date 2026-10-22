# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Persist live public reasoning independently from terminal provenance."""

from alembic import op

revision = "0012_prism_reasoning_entries"
down_revision = "0011_create_skills"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE prism_reasoning_entries (
            id UUID PRIMARY KEY,
            run_id UUID NOT NULL REFERENCES prism_runs(id) ON DELETE CASCADE,
            sequence INTEGER NOT NULL CHECK (sequence > 0),
            source_event_key TEXT NOT NULL,
            event_kind TEXT NOT NULL CHECK (event_kind IN ('run','stage','model')),
            observed_at TIMESTAMPTZ NOT NULL,
            source JSONB NOT NULL,
            source_digest TEXT NOT NULL CHECK (source_digest ~ '^sha256:[0-9a-f]{64}$'),
            presentation JSONB NOT NULL DEFAULT '{"status":"pending","icon_id":"information"}'::jsonb,
            UNIQUE(run_id, source_event_key), UNIQUE(run_id, sequence),
            CHECK (presentation->>'status' IN ('pending','ready','unavailable'))
        )
    """)
    op.execute("""
        CREATE FUNCTION protect_prism_reasoning_source() RETURNS trigger AS $$
        BEGIN
            IF (NEW.id, NEW.run_id, NEW.sequence, NEW.source_event_key, NEW.event_kind,
                NEW.observed_at, NEW.source, NEW.source_digest)
                IS DISTINCT FROM
               (OLD.id, OLD.run_id, OLD.sequence, OLD.source_event_key, OLD.event_kind,
                OLD.observed_at, OLD.source, OLD.source_digest)
               OR OLD.presentation->>'status' <> 'pending'
               OR NEW.presentation->>'status' = 'pending' THEN
                RAISE EXCEPTION 'reasoning source is immutable; presentation settles once';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER prism_reasoning_immutable BEFORE UPDATE ON prism_reasoning_entries
        FOR EACH ROW EXECUTE FUNCTION protect_prism_reasoning_source();
    """)
    # Trigger notifications also cover state changes/deletion from another API process.
    op.execute("""
        CREATE FUNCTION notify_prism_reasoning() RETURNS trigger AS $$
        BEGIN
            IF TG_TABLE_NAME = 'prism_runs' THEN
                PERFORM pg_notify('prism_reasoning', COALESCE(NEW.id, OLD.id)::text);
            ELSE
                PERFORM pg_notify('prism_reasoning', COALESCE(NEW.run_id, OLD.run_id)::text);
            END IF;
            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER prism_reasoning_changed AFTER INSERT OR UPDATE ON prism_reasoning_entries
        FOR EACH ROW EXECUTE FUNCTION notify_prism_reasoning();
        CREATE TRIGGER prism_reasoning_run_changed AFTER UPDATE OR DELETE ON prism_runs
        FOR EACH ROW EXECUTE FUNCTION notify_prism_reasoning();
    """)


def downgrade():
    op.execute("DROP TRIGGER prism_reasoning_run_changed ON prism_runs")
    op.execute("DROP TABLE prism_reasoning_entries")
    op.execute("DROP FUNCTION protect_prism_reasoning_source()")
    op.execute("DROP FUNCTION notify_prism_reasoning()")
