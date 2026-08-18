VERSION = 13
DESCRIPTION = "architecture generation leases and snapshot integrity guards"

SQL = """
CREATE TABLE IF NOT EXISTS architecture_generation_state (
    project          TEXT NOT NULL,
    environment      TEXT NOT NULL CHECK (environment IN ('all', 'dev', 'prod')),
    local_run_date   TEXT NOT NULL,
    source_digest    TEXT NOT NULL,
    status           TEXT NOT NULL CHECK (status IN
                     ('running', 'success', 'failed', 'cancelled', 'skipped')),
    attempt_id       TEXT NOT NULL,
    started_at       TEXT NOT NULL DEFAULT (datetime('now')),
    finished_at      TEXT,
    lease_expires_at TEXT,
    snapshot_id      TEXT,
    last_error       TEXT,
    PRIMARY KEY (project, environment)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_architecture_one_published
    ON architecture_snapshots (project, environment)
    WHERE status = 'published';

CREATE TRIGGER IF NOT EXISTS trg_architecture_snapshot_validate_insert
BEFORE INSERT ON architecture_snapshots
WHEN NEW.environment NOT IN ('all', 'dev', 'prod')
  OR NEW.status NOT IN ('draft', 'published', 'archived')
  OR NEW.source_count < 0
  OR NEW.evidence_coverage < 0 OR NEW.evidence_coverage > 1
BEGIN
    SELECT RAISE(ABORT, 'invalid architecture snapshot metadata');
END;

CREATE TRIGGER IF NOT EXISTS trg_architecture_snapshot_validate_update
BEFORE UPDATE OF environment, status, source_count, evidence_coverage
ON architecture_snapshots
WHEN NEW.environment NOT IN ('all', 'dev', 'prod')
  OR NEW.status NOT IN ('draft', 'published', 'archived')
  OR NEW.source_count < 0
  OR NEW.evidence_coverage < 0 OR NEW.evidence_coverage > 1
BEGIN
    SELECT RAISE(ABORT, 'invalid architecture snapshot metadata');
END;
"""


def run(conn):
    table = conn.execute("""
        SELECT 1 FROM sqlite_master
        WHERE type = 'table' AND name = 'architecture_snapshots'
    """).fetchone()
    if not table:
        raise RuntimeError('migration 013 requires architecture_snapshots from migration 012')

    invalid = conn.execute("""
        SELECT 1 FROM architecture_snapshots
        WHERE environment NOT IN ('all', 'dev', 'prod')
           OR status NOT IN ('draft', 'published', 'archived')
           OR source_count < 0
           OR evidence_coverage < 0 OR evidence_coverage > 1
        LIMIT 1
    """).fetchone()
    if invalid:
        raise RuntimeError('existing architecture snapshot metadata is invalid')

    duplicate = conn.execute("""
        SELECT 1 FROM architecture_snapshots
        WHERE status = 'published'
        GROUP BY project, environment HAVING COUNT(*) > 1
        LIMIT 1
    """).fetchone()
    if duplicate:
        raise RuntimeError('multiple published architecture snapshots require review')

    conn.executescript(SQL)
    required = {
        'project', 'environment', 'local_run_date', 'source_digest', 'status',
        'attempt_id', 'lease_expires_at', 'snapshot_id',
    }
    columns = {
        row[1] for row in conn.execute(
            'PRAGMA table_info(architecture_generation_state)').fetchall()
    }
    if required - columns:
        raise RuntimeError('architecture generation state schema is incomplete')
    conn.commit()
