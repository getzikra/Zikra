"""Regression tests for the SQLite to PostgreSQL cutover tooling."""
import sqlite3
import struct
import tempfile
import unittest
from pathlib import Path

import sqlite_vec

from scripts.migrate_sqlite_to_postgres import (
    BUSINESS_TABLES,
    read_sqlite_snapshot,
    sha256_file,
    validate_source_snapshot,
)
from zikra.db_postgres import _PG_TABLES


def _source_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    conn.executescript(
        """
        CREATE TABLE memories (
            id TEXT PRIMARY KEY, project TEXT NOT NULL, module TEXT,
            memory_type TEXT NOT NULL, title TEXT NOT NULL, content_md TEXT NOT NULL,
            tags TEXT NOT NULL, resolution TEXT, created_by TEXT,
            confidence_score REAL, access_count INTEGER, searchable INTEGER,
            resolved INTEGER, pending_review INTEGER, created_at TEXT,
            updated_at TEXT, last_accessed_at TEXT, pinned INTEGER
        );
        CREATE VIRTUAL TABLE memories_vec USING vec0(embedding float[1536]);
        CREATE TABLE prompt_runs (
            id TEXT PRIMARY KEY, project TEXT, runner TEXT, prompt_name TEXT,
            status TEXT, output_summary TEXT, tokens_input INTEGER,
            tokens_output INTEGER, cost_usd REAL, created_at TEXT,
            prompt_id TEXT, tokens_cache_read INTEGER,
            tokens_cache_creation INTEGER, session_id TEXT
        );
        CREATE TABLE error_log (
            id TEXT PRIMARY KEY, project TEXT, runner TEXT, error_type TEXT,
            message TEXT, stack_trace TEXT, context_md TEXT, created_at TEXT
        );
        CREATE TABLE access_tokens (
            id TEXT PRIMARY KEY, token TEXT, person_name TEXT, role TEXT,
            active INTEGER, created_at TEXT, token_name TEXT, project_scope TEXT
        );
        CREATE TABLE token_hits (id TEXT PRIMARY KEY, label TEXT, command TEXT, ts TEXT);
        CREATE TABLE retrievals (id TEXT PRIMARY KEY, memory_id TEXT, source TEXT, query TEXT, ts TEXT);
        CREATE TABLE pending_runs (runner TEXT, project TEXT, prompt_id TEXT, created_at TEXT, PRIMARY KEY(runner, project));
        CREATE TABLE memory_links (from_id TEXT, to_id TEXT, anchor TEXT, PRIMARY KEY(from_id, to_id));
        CREATE TABLE session_ingests (
            id TEXT PRIMARY KEY, runner TEXT, project TEXT, session_id TEXT,
            cwd TEXT, transcript_tail TEXT, status TEXT, error TEXT,
            memories_created INTEGER, created_at TEXT, distilled_at TEXT
        );
        CREATE TABLE schema_versions (version INTEGER PRIMARY KEY, description TEXT, applied_at TEXT);
        """
    )
    conn.execute(
        """INSERT INTO memories VALUES
        ('m1','proj',NULL,'decision','Title','Body','[]',NULL,'test',1.0,2,1,0,0,
         '2026-01-01 00:00:00','2026-01-02 00:00:00',NULL,1)"""
    )
    vector = [float(i) / 1536 for i in range(1536)]
    conn.execute(
        "INSERT INTO memories_vec(rowid, embedding) VALUES (1, ?)",
        [struct.pack("1536f", *vector)],
    )
    conn.execute(
        "INSERT INTO access_tokens VALUES ('t1','secret','Pi','developer',1,'2026-01-01',NULL,'proj')"
    )
    conn.execute(
        "INSERT INTO schema_versions VALUES (10,'session ingests','2026-01-01')"
    )
    conn.commit()
    return conn


class SQLitePostgresMigrationTests(unittest.TestCase):
    def test_postgres_vector_dimension_matches_default_embedding_model(self):
        self.assertIn("vector(1536)", _PG_TABLES)
        self.assertNotIn("halfvec(3072)", _PG_TABLES)
        self.assertIn("confidence_score DOUBLE PRECISION", _PG_TABLES)
        self.assertIn("cost_usd               DOUBLE PRECISION", _PG_TABLES)
        self.assertIn("CREATE TABLE IF NOT EXISTS deployment_state", _PG_TABLES)

    def test_snapshot_preserves_every_business_table_and_embedding(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "zikra.db"
            conn = _source_db(source)
            conn.close()

            snapshot = read_sqlite_snapshot(source)
            validate_source_snapshot(snapshot)

            self.assertEqual(set(snapshot.rows), set(BUSINESS_TABLES))
            self.assertEqual(len(snapshot.rows["memories"]), 1)
            self.assertEqual(len(snapshot.rows["memories"][0]["embedding"]), 1536)
            self.assertNotEqual(snapshot.rows["memories"][0]["embedding"][1], 0.0)
            self.assertEqual(snapshot.rows["access_tokens"][0]["token"], "secret")
            self.assertEqual(snapshot.rows["schema_versions"][0]["version"], 10)

    def test_snapshot_digest_must_match_approved_value(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "zikra.db"
            conn = _source_db(source)
            conn.close()
            approved = sha256_file(source)
            read_sqlite_snapshot(source, approved)
            with self.assertRaisesRegex(ValueError, "approved digest"):
                read_sqlite_snapshot(source, "0" * 64)
            linked = Path(directory) / "linked.db"
            linked.symlink_to(source)
            with self.assertRaisesRegex(ValueError, "non-linked"):
                read_sqlite_snapshot(linked, approved)

    def test_snapshot_rejects_missing_or_unexpected_source_columns(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "zikra.db"
            conn = _source_db(source)
            conn.execute("ALTER TABLE token_hits ADD COLUMN unreviewed TEXT")
            conn.commit()
            conn.close()
            with self.assertRaisesRegex(ValueError, "source schema mismatch for token_hits"):
                read_sqlite_snapshot(source)


if __name__ == "__main__":
    unittest.main()
