"""
Migration system tests.
Run with: python -m pytest zikra/tests/test_migrations.py -v
"""
import sqlite3
import sqlite_vec
import tempfile
from pathlib import Path

from zikra.migrate import run_migrations


def _make_in_memory_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(':memory:', check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    return conn


def _table_exists(conn, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", [name]
    ).fetchone()
    return row is not None


def test_fresh_install_creates_all_tables():
    """All expected tables exist after running migrations from scratch."""
    conn = _make_in_memory_conn()
    run_migrations(conn)

    for table in ('memories', 'prompt_runs', 'error_log', 'access_tokens', 'schema_versions'):
        assert _table_exists(conn, table), f"Table '{table}' was not created"
    conn.close()


def test_schema_versions_populated():
    """schema_versions has rows for every migration that ran."""
    conn = _make_in_memory_conn()
    run_migrations(conn)

    rows = conn.execute("SELECT version FROM schema_versions ORDER BY version").fetchall()
    versions = [r['version'] for r in rows]
    assert len(versions) >= 2, f"Expected at least 2 migrations, got {versions}"
    assert 1 in versions
    assert 2 in versions
    conn.close()


def test_idempotent_double_run():
    """Running migrations twice raises no error and adds no duplicate rows."""
    conn = _make_in_memory_conn()
    run_migrations(conn)

    count_before = conn.execute("SELECT COUNT(*) FROM schema_versions").fetchone()[0]
    run_migrations(conn)  # second run — must be silent
    count_after = conn.execute("SELECT COUNT(*) FROM schema_versions").fetchone()[0]

    assert count_before == count_after, "Duplicate schema_versions rows added on second run"
    conn.close()


def test_fake_migration_applied():
    """A fake migration 999 in a temp dir gets applied on top of real migrations."""
    conn = _make_in_memory_conn()

    # Run real migrations first using the package migrations dir
    real_dir = Path(__file__).parent.parent / 'migrations'
    run_migrations(conn, migrations_dir=real_dir)

    # Create a temp dir with only the fake migration
    with tempfile.TemporaryDirectory() as tmpdir:
        fake_path = Path(tmpdir) / '999_add_fake_table.py'
        fake_path.write_text(
            'VERSION = 999\n'
            'DESCRIPTION = "add fake_table for testing"\n'
            'SQL = "CREATE TABLE IF NOT EXISTS fake_table (id INTEGER PRIMARY KEY);"\n'
        )
        run_migrations(conn, migrations_dir=Path(tmpdir))

    assert _table_exists(conn, 'fake_table'), "fake_table was not created by migration 999"

    row = conn.execute(
        "SELECT description FROM schema_versions WHERE version = 999"
    ).fetchone()
    assert row is not None, "schema_versions has no row for migration 999"
    assert 'fake' in row['description'].lower()
    conn.close()


def test_schema_versions_rows_correct():
    """schema_versions rows match the actual migration files."""
    conn = _make_in_memory_conn()
    run_migrations(conn)

    rows = conn.execute(
        "SELECT version, description FROM schema_versions ORDER BY version"
    ).fetchall()

    assert rows[0]['version'] == 1
    assert 'initial schema' in rows[0]['description'].lower()

    assert rows[1]['version'] == 2
    assert 'schema_versions' in rows[1]['description'].lower()
    conn.close()
