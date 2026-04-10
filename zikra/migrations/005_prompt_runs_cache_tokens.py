VERSION = 5
DESCRIPTION = "prompt_runs: add prompt_id + cache token columns for v1.0.5 run tracking"

SQL = """
ALTER TABLE prompt_runs ADD COLUMN prompt_id TEXT;
ALTER TABLE prompt_runs ADD COLUMN tokens_cache_read INTEGER;
ALTER TABLE prompt_runs ADD COLUMN tokens_cache_creation INTEGER;
CREATE INDEX IF NOT EXISTS idx_prompt_runs_prompt_id ON prompt_runs(prompt_id);
CREATE INDEX IF NOT EXISTS idx_prompt_runs_prompt_name ON prompt_runs(prompt_name);
"""


def run(conn):
    import sqlite3
    # SQLite ALTER TABLE ADD COLUMN errors if column already exists — swallow those.
    for stmt in SQL.strip().split(';'):
        stmt = stmt.strip()
        if not stmt:
            continue
        try:
            conn.execute(stmt)
        except sqlite3.OperationalError as e:
            if 'duplicate column' in str(e).lower() or 'already exists' in str(e).lower():
                continue
            raise
    conn.commit()
