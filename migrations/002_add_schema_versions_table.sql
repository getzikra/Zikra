-- ─────────────────────────────────────────────────────────────────────────────
-- Migration 002 — Add schema_versions table
-- Idempotent. Safe to run multiple times.
-- ─────────────────────────────────────────────────────────────────────────────

BEGIN;

CREATE TABLE IF NOT EXISTS zikra.schema_versions (
    version     INTEGER     NOT NULL PRIMARY KEY,
    description TEXT        NOT NULL,
    applied_at  TIMESTAMPTZ DEFAULT NOW()
);

COMMENT ON TABLE zikra.schema_versions IS
    'Canonical migration version tracking table used by scripts/migrate.sh';

INSERT INTO zikra.migrations (version, description)
VALUES (2, 'add schema_versions table')
ON CONFLICT (version) DO NOTHING;

COMMIT;
