VERSION = 12
DESCRIPTION = "architecture decision integrity and generated snapshots"

SQL = """
CREATE TABLE IF NOT EXISTS architecture_snapshots (
    id                TEXT PRIMARY KEY,
    project           TEXT NOT NULL,
    environment       TEXT NOT NULL DEFAULT 'all',
    status            TEXT NOT NULL DEFAULT 'draft',
    model             TEXT,
    prompt_version    TEXT,
    summary           TEXT,
    document_json     TEXT NOT NULL,
    source_digest     TEXT,
    source_count      INTEGER NOT NULL DEFAULT 0,
    evidence_coverage REAL NOT NULL DEFAULT 0,
    generated_at      TEXT DEFAULT (datetime('now')),
    published_at      TEXT,
    created_by        TEXT
);

CREATE INDEX IF NOT EXISTS idx_architecture_snapshots_project
    ON architecture_snapshots (project, environment, status, generated_at DESC);

CREATE TABLE IF NOT EXISTS architecture_project_state (
    project       TEXT PRIMARY KEY,
    last_run_at   TEXT,
    last_status   TEXT,
    last_error    TEXT,
    last_snapshot_id TEXT
);
"""


def run(conn):
    # Migration 011 was already applied on the first production rollout. Keep
    # this guard here so upgrades gain the architecture discriminator too.
    mem_cols = [r[1] for r in conn.execute("PRAGMA table_info(memories)").fetchall()]
    if 'decision_kind' not in mem_cols:
        conn.execute("ALTER TABLE memories ADD COLUMN decision_kind TEXT")

    conn.executescript(SQL)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_memories_arch
        ON memories (project, module, status, memory_type, decision_kind)
    """)
    conn.commit()
