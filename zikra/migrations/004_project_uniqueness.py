import sqlite3

VERSION = 4
DESCRIPTION = "fix project isolation: UNIQUE(title, memory_type) -> UNIQUE(title, memory_type, project)"

SQL = ""  # unused — run() handles this migration


def run(conn: sqlite3.Connection):
    try:
        conn.execute("DROP INDEX IF EXISTS idx_memories_title_type")
        conn.commit()
    except sqlite3.OperationalError:
        pass

    try:
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_memories_title_type_project "
            "ON memories(title, memory_type, project)"
        )
        conn.commit()
    except sqlite3.OperationalError as e:
        if "already exists" in str(e).lower():
            pass  # index already present — idempotent
        else:
            raise
