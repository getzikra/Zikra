import sqlite3

VERSION = 3
DESCRIPTION = "add token_name column to access_tokens"

SQL = ""  # unused — run() handles this migration


def run(conn: sqlite3.Connection):
    try:
        conn.execute("ALTER TABLE access_tokens ADD COLUMN token_name TEXT")
        conn.commit()
    except sqlite3.OperationalError as e:
        if "duplicate column" in str(e).lower():
            pass  # column already exists — idempotent
        else:
            raise
