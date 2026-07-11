VERSION = 9
DESCRIPTION = "retrievals log + memories.last_accessed_at/pinned + prompt_runs.session_id"

SQL = """
CREATE TABLE IF NOT EXISTS retrievals (
    id        TEXT PRIMARY KEY,
    memory_id TEXT NOT NULL,
    source    TEXT NOT NULL,
    query     TEXT,
    ts        TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_retrievals_memory_ts ON retrievals (memory_id, ts DESC);
CREATE INDEX IF NOT EXISTS idx_retrievals_ts ON retrievals (ts DESC);

ALTER TABLE memories ADD COLUMN last_accessed_at TEXT;
ALTER TABLE memories ADD COLUMN pinned INTEGER DEFAULT 0;
ALTER TABLE prompt_runs ADD COLUMN session_id TEXT;
"""


def run(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS retrievals (
            id        TEXT PRIMARY KEY,
            memory_id TEXT NOT NULL,
            source    TEXT NOT NULL,
            query     TEXT,
            ts        TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_retrievals_memory_ts ON retrievals (memory_id, ts DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_retrievals_ts ON retrievals (ts DESC)")

    # ADD COLUMN is not idempotent in SQLite — guard manually
    mem_cols = [r[1] for r in conn.execute("PRAGMA table_info(memories)").fetchall()]
    if 'last_accessed_at' not in mem_cols:
        conn.execute("ALTER TABLE memories ADD COLUMN last_accessed_at TEXT")
    if 'pinned' not in mem_cols:
        conn.execute("ALTER TABLE memories ADD COLUMN pinned INTEGER DEFAULT 0")

    run_cols = [r[1] for r in conn.execute("PRAGMA table_info(prompt_runs)").fetchall()]
    if 'session_id' not in run_cols:
        conn.execute("ALTER TABLE prompt_runs ADD COLUMN session_id TEXT")

    # One run row per (runner, session): hook and watcher upsert into the same row
    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_prompt_runs_runner_session
        ON prompt_runs (runner, session_id) WHERE session_id IS NOT NULL
    """)

    conn.commit()
