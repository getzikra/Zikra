VERSION = 6
DESCRIPTION = "pending_runs: server-side handshake for prompt_id <-> run linkage"

SQL = """
CREATE TABLE IF NOT EXISTS pending_runs (
    runner     TEXT NOT NULL,
    project    TEXT NOT NULL DEFAULT 'global',
    prompt_id  TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (runner, project)
);
"""
