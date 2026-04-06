import sqlite3
import importlib.util
import re
from pathlib import Path


def run_migrations(conn: sqlite3.Connection, migrations_dir: Path = None):
    """Run all pending schema migrations against the given SQLite connection.

    Rules:
    - Additive only: ADD COLUMN, CREATE TABLE, CREATE INDEX
    - Idempotent: safe to run twice
    - Never DROP, ALTER to remove, or TRUNCATE

    Migration files in migrations_dir must define:
        VERSION     = int   (e.g. 1, 2, 3)
        DESCRIPTION = str   (e.g. "add confidence column")
        SQL         = str   (the SQL statements to execute)
    """
    if migrations_dir is None:
        migrations_dir = Path(__file__).parent / 'migrations'

    # Step 1: Ensure schema_versions table exists
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_versions (
            version INTEGER PRIMARY KEY,
            description TEXT NOT NULL,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()

    # Step 2: Get current max applied version (0 if none)
    row = conn.execute("SELECT MAX(version) FROM schema_versions").fetchone()
    current_version = row[0] if row[0] is not None else 0

    # Step 3: Scan for NNN_*.py migration files
    migration_files = sorted(migrations_dir.glob('[0-9][0-9][0-9]_*.py'))

    # Step 4: Apply each migration with version > current
    for path in migration_files:
        match = re.match(r'^(\d+)_', path.name)
        if not match:
            continue
        version = int(match.group(1))
        if version <= current_version:
            continue

        spec = importlib.util.spec_from_file_location(f'_migration_{version}', path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        if hasattr(mod, 'run'):
            mod.run(conn)
        else:
            conn.executescript(mod.SQL)

        conn.execute(
            "INSERT OR IGNORE INTO schema_versions (version, description) VALUES (?, ?)",
            [version, mod.DESCRIPTION]
        )
        conn.commit()
        print(f"Applied migration {version:03d}: {mod.DESCRIPTION}")
