VERSION = 8
DESCRIPTION = "token_hits table for usage tracking + project_scope on access_tokens"

SQL = """
CREATE TABLE IF NOT EXISTS token_hits (
    id      TEXT PRIMARY KEY,
    label   TEXT NOT NULL,
    command TEXT NOT NULL,
    ts      TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_token_hits_label_ts ON token_hits (label, ts DESC);
CREATE INDEX IF NOT EXISTS idx_token_hits_ts ON token_hits (ts DESC);

ALTER TABLE access_tokens ADD COLUMN project_scope TEXT;
"""


def run(conn):
    import sqlite3
    conn.execute("""
        CREATE TABLE IF NOT EXISTS token_hits (
            id      TEXT PRIMARY KEY,
            label   TEXT NOT NULL,
            command TEXT NOT NULL,
            ts      TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_token_hits_label_ts ON token_hits (label, ts DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_token_hits_ts ON token_hits (ts DESC)")

    # ADD COLUMN is not idempotent in SQLite — guard manually
    cols = [r[1] for r in conn.execute("PRAGMA table_info(access_tokens)").fetchall()]
    if 'project_scope' not in cols:
        conn.execute("ALTER TABLE access_tokens ADD COLUMN project_scope TEXT")

    conn.commit()
