VERSION = 11
DESCRIPTION = "architecture decisions: typed decision metadata + repo_sync_state"

SQL = """
CREATE TABLE IF NOT EXISTS repo_sync_state (
    project            TEXT NOT NULL,
    repo_path          TEXT NOT NULL,
    last_synced_commit TEXT,
    synced_at          TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (project, repo_path)
);

CREATE INDEX IF NOT EXISTS idx_memories_arch
    ON memories (project, module, status, memory_type);
"""


def run(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS repo_sync_state (
            project            TEXT NOT NULL,
            repo_path          TEXT NOT NULL,
            last_synced_commit TEXT,
            synced_at          TEXT DEFAULT (datetime('now')),
            PRIMARY KEY (project, repo_path)
        )
    """)

    # ADD COLUMN is not idempotent in SQLite — guard manually
    mem_cols = [r[1] for r in conn.execute("PRAGMA table_info(memories)").fetchall()]
    if 'status' not in mem_cols:
        conn.execute("ALTER TABLE memories ADD COLUMN status TEXT NOT NULL DEFAULT 'current'")
    if 'supersedes_id' not in mem_cols:
        conn.execute("ALTER TABLE memories ADD COLUMN supersedes_id TEXT")
    if 'environment' not in mem_cols:
        conn.execute("ALTER TABLE memories ADD COLUMN environment TEXT")
    if 'evidence' not in mem_cols:
        conn.execute("ALTER TABLE memories ADD COLUMN evidence TEXT")
    if 'decision_kind' not in mem_cols:
        conn.execute("ALTER TABLE memories ADD COLUMN decision_kind TEXT")

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_memories_arch
        ON memories (project, module, status, memory_type, decision_kind)
    """)

    conn.commit()
