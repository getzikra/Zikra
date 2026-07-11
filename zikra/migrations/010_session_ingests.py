VERSION = 10
DESCRIPTION = "session_ingests table for server-side transcript distillation"

SQL = """
CREATE TABLE IF NOT EXISTS session_ingests (
    id               TEXT PRIMARY KEY,
    runner           TEXT NOT NULL,
    project          TEXT NOT NULL DEFAULT 'global',
    session_id       TEXT,
    cwd              TEXT,
    transcript_tail  TEXT NOT NULL,
    status           TEXT NOT NULL DEFAULT 'pending',
    error            TEXT,
    memories_created INTEGER DEFAULT 0,
    created_at       TEXT DEFAULT (datetime('now')),
    distilled_at     TEXT
);

CREATE INDEX IF NOT EXISTS idx_session_ingests_status ON session_ingests (status, created_at);
CREATE INDEX IF NOT EXISTS idx_session_ingests_session ON session_ingests (runner, session_id);
"""


def run(conn):
    conn.executescript(SQL)
    conn.commit()
