#!/usr/bin/env python3
"""Migrate a complete Zikra SQLite snapshot into an empty PostgreSQL database.

The source is opened read-only, integrity checked, and loaded into memory before
PostgreSQL is changed. The destination import is one transaction. The script
prints counts only; it never prints row content, tokens, transcript tails, or
embeddings.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import hashlib
import os
import sqlite3
import stat
import struct
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import sqlite_vec

BUSINESS_TABLES = (
    "memories",
    "prompt_runs",
    "error_log",
    "access_tokens",
    "token_hits",
    "retrievals",
    "pending_runs",
    "memory_links",
    "session_ingests",
    "schema_versions",
)

TABLE_COLUMNS = {
    "memories": (
        "id", "project", "module", "memory_type", "title", "content_md",
        "tags", "resolution", "created_by", "confidence_score", "access_count",
        "searchable", "resolved", "pending_review", "created_at", "updated_at",
        "last_accessed_at", "pinned", "embedding",
    ),
    "prompt_runs": (
        "id", "project", "runner", "prompt_id", "prompt_name", "status",
        "output_summary", "tokens_input", "tokens_output", "tokens_cache_read",
        "tokens_cache_creation", "cost_usd", "session_id", "created_at",
    ),
    "error_log": (
        "id", "project", "runner", "error_type", "message", "stack_trace",
        "context_md", "created_at",
    ),
    "access_tokens": (
        "id", "token", "person_name", "role", "active", "token_name",
        "project_scope", "created_at",
    ),
    "token_hits": ("id", "label", "command", "ts"),
    "retrievals": ("id", "memory_id", "source", "query", "ts"),
    "pending_runs": ("runner", "project", "prompt_id", "created_at"),
    "memory_links": ("from_id", "to_id", "anchor"),
    "session_ingests": (
        "id", "runner", "project", "session_id", "cwd", "transcript_tail",
        "status", "error", "memories_created", "created_at", "distilled_at",
    ),
    "schema_versions": ("version", "description", "applied_at"),
}

TABLE_KEYS = {
    "memories": ("id",),
    "prompt_runs": ("id",),
    "error_log": ("id",),
    "access_tokens": ("id",),
    "token_hits": ("id",),
    "retrievals": ("id",),
    "pending_runs": ("runner", "project"),
    "memory_links": ("from_id", "to_id"),
    "session_ingests": ("id",),
    "schema_versions": ("version",),
}

TIMESTAMP_COLUMNS = {
    "memories": {"created_at", "updated_at", "last_accessed_at"},
    "prompt_runs": {"created_at"},
    "error_log": {"created_at"},
    "access_tokens": {"created_at"},
    "token_hits": {"ts"},
    "retrievals": {"ts"},
    "pending_runs": {"created_at"},
    "session_ingests": {"created_at", "distilled_at"},
    "schema_versions": {"applied_at"},
}


@dataclass(frozen=True)
class SQLiteSnapshot:
    source: Path
    rows: dict[str, list[dict[str, Any]]]
    integrity: str

    @property
    def counts(self) -> dict[str, int]:
        return {name: len(rows) for name, rows in self.rows.items()}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _connect_snapshot_copy(path: Path, workspace: Path, expected_sha256: str | None) -> sqlite3.Connection:
    normalized = None
    if expected_sha256 is not None:
        normalized = expected_sha256.strip().lower()
        if len(normalized) != 64 or any(character not in "0123456789abcdef" for character in normalized):
            raise ValueError("approved source SHA-256 must be 64 lowercase hexadecimal characters")

    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise ValueError("source must be an existing non-linked SQLite snapshot") from error
    local_copy = workspace / "zikra.db"
    digest = hashlib.sha256()
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError("source must be a regular SQLite snapshot")
        if metadata.st_size > 10 * 1024 * 1024 * 1024:
            raise ValueError("source snapshot exceeds the 10 GiB migration limit")
        with os.fdopen(descriptor, "rb", closefd=False) as source, local_copy.open("xb") as destination:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
                destination.write(chunk)
            destination.flush()
            os.fsync(destination.fileno())
    finally:
        os.close(descriptor)
    if normalized is not None and digest.hexdigest() != normalized:
        local_copy.unlink(missing_ok=True)
        raise ValueError("source snapshot SHA-256 does not match the approved digest")
    local_copy.chmod(0o600)
    conn = sqlite3.connect(local_copy)
    conn.row_factory = sqlite3.Row
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    return conn


def _decode_embedding(blob: bytes | None) -> list[float] | None:
    if blob is None:
        return None
    if len(blob) != 1536 * 4:
        raise ValueError(f"unexpected embedding byte length: {len(blob)}")
    return list(struct.unpack("<1536f", blob))


def read_sqlite_snapshot(path: Path, expected_sha256: str | None = None) -> SQLiteSnapshot:
    with tempfile.TemporaryDirectory(prefix="zikra-migrate-") as directory:
        conn = _connect_snapshot_copy(path, Path(directory), expected_sha256)
        try:
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
            table_names = {
                row[0] for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            missing = set(BUSINESS_TABLES) - table_names
            if missing:
                raise ValueError("source is missing required tables: " + ", ".join(sorted(missing)))
            for table in BUSINESS_TABLES:
                actual_columns = {
                    row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')
                }
                expected_columns = set(TABLE_COLUMNS[table]) - {"embedding"}
                if actual_columns != expected_columns:
                    missing_columns = expected_columns - actual_columns
                    unexpected_columns = actual_columns - expected_columns
                    details = []
                    if missing_columns:
                        details.append("missing=" + ",".join(sorted(missing_columns)))
                    if unexpected_columns:
                        details.append("unexpected=" + ",".join(sorted(unexpected_columns)))
                    raise ValueError(f"source schema mismatch for {table}: " + " ".join(details))

            vectors = {
                row["rowid"]: _decode_embedding(row["embedding"])
                for row in conn.execute("SELECT rowid, embedding FROM memories_vec")
            }
            rows: dict[str, list[dict[str, Any]]] = {}
            for table in BUSINESS_TABLES:
                if table == "memories":
                    values = []
                    for row in conn.execute("SELECT rowid AS _rowid, * FROM memories ORDER BY id"):
                        item = dict(row)
                        item["embedding"] = vectors.get(item.pop("_rowid"))
                        values.append(item)
                    rows[table] = values
                else:
                    rows[table] = [
                        dict(row) for row in conn.execute(f'SELECT * FROM "{table}" ORDER BY 1')
                    ]
            return SQLiteSnapshot(source=path.resolve(), rows=rows, integrity=integrity)
        finally:
            conn.close()


def validate_source_snapshot(snapshot: SQLiteSnapshot) -> None:
    if snapshot.integrity != "ok":
        raise ValueError(f"SQLite integrity check failed: {snapshot.integrity}")
    memory_ids = {row["id"] for row in snapshot.rows["memories"]}
    if len(memory_ids) != len(snapshot.rows["memories"]):
        raise ValueError("duplicate memory IDs in source")
    vector_count = sum(row["embedding"] is not None for row in snapshot.rows["memories"])
    if vector_count != len(snapshot.rows["memories"]):
        raise ValueError("one or more source memories has no vector row")
    for row in snapshot.rows["memory_links"]:
        if row["from_id"] not in memory_ids or row["to_id"] not in memory_ids:
            raise ValueError("memory_links contains an orphaned memory ID")


def _timestamp(value: Any) -> Any:
    if value in (None, "") or isinstance(value, dt.datetime):
        return value or None
    text = str(value).strip().replace("Z", "+00:00")
    parsed = dt.datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed


def _pg_value(table: str, column: str, value: Any) -> Any:
    if column in TIMESTAMP_COLUMNS.get(table, set()):
        return _timestamp(value)
    if column == "embedding":
        if value is None:
            return None
        return "[" + ",".join(repr(float(component)) for component in value) + "]"
    return value


def _comparable(value: Any) -> Any:
    if isinstance(value, dt.datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=dt.timezone.utc)
        return value.astimezone(dt.timezone.utc).isoformat()
    return value


def _vector_bytes(value: str | None) -> bytes | None:
    if value is None:
        return None
    components = [float(component) for component in value.strip("[]").split(",")]
    if len(components) != 1536:
        raise RuntimeError("destination contains an embedding with the wrong dimension")
    return struct.pack("<1536f", *components)


async def _destination_counts(conn) -> dict[str, int]:
    return {
        table: await conn.fetchval(f'SELECT count(*) FROM "{table}"')
        for table in BUSINESS_TABLES
    }


async def migrate(snapshot: SQLiteSnapshot) -> dict[str, int]:
    from zikra.db_postgres import init_pg

    pool = await init_pg()
    try:
        async with pool.acquire() as conn:
            existing = await _destination_counts(conn)
            occupied = {table: count for table, count in existing.items() if count}
            if occupied:
                raise RuntimeError(
                    "destination is not empty: "
                    + ", ".join(f"{table}={count}" for table, count in occupied.items())
                )

            async with conn.transaction():
                for table in BUSINESS_TABLES:
                    columns = TABLE_COLUMNS[table]
                    rows = snapshot.rows[table]
                    if not rows:
                        continue
                    placeholders = []
                    for index, column in enumerate(columns, start=1):
                        cast = "::vector" if column == "embedding" else ""
                        placeholders.append(f"${index}{cast}")
                    sql = (
                        f'INSERT INTO "{table}" ('
                        + ",".join(f'"{column}"' for column in columns)
                        + ") VALUES ("
                        + ",".join(placeholders)
                        + ")"
                    )
                    values = [
                        tuple(_pg_value(table, column, row.get(column)) for column in columns)
                        for row in rows
                    ]
                    await conn.executemany(sql, values)

                actual = await _destination_counts(conn)
                if actual != snapshot.counts:
                    raise RuntimeError(
                        "row-count verification failed: "
                        + ", ".join(
                            f"{table} source={snapshot.counts[table]} destination={actual[table]}"
                            for table in BUSINESS_TABLES
                            if snapshot.counts[table] != actual[table]
                        )
                    )

                for table in BUSINESS_TABLES:
                    keys = TABLE_KEYS[table]
                    expected = {
                        tuple(str(row[key]) for key in keys)
                        for row in snapshot.rows[table]
                    }
                    selection = ",".join(f'"{key}"' for key in keys)
                    actual = {
                        tuple(str(record[key]) for key in keys)
                        for record in await conn.fetch(
                            f'SELECT {selection} FROM "{table}"'
                        )
                    }
                    if actual != expected:
                        raise RuntimeError(f"identifier verification failed for {table}")

                for table in BUSINESS_TABLES:
                    columns = tuple(column for column in TABLE_COLUMNS[table] if column != "embedding")
                    selection = ",".join(f'"{column}"' for column in columns)
                    actual_rows = await conn.fetch(f'SELECT {selection} FROM "{table}"')
                    keys = TABLE_KEYS[table]
                    expected_by_key = {
                        tuple(str(row[key]) for key in keys): {
                            column: _comparable(_pg_value(table, column, row.get(column)))
                            for column in columns
                        }
                        for row in snapshot.rows[table]
                    }
                    actual_by_key = {
                        tuple(str(record[key]) for key in keys): {
                            column: _comparable(record[column]) for column in columns
                        }
                        for record in actual_rows
                    }
                    if actual_by_key != expected_by_key:
                        raise RuntimeError(f"row-content verification failed for {table}")

                vector_rows = await conn.fetch(
                    "SELECT id, vector_dims(embedding) AS dims, embedding::text AS embedding FROM memories"
                )
                source_vectors = {
                    row["id"]: struct.pack("<1536f", *row["embedding"])
                    for row in snapshot.rows["memories"]
                }
                actual_vectors = {
                    row["id"]: _vector_bytes(row["embedding"])
                    for row in vector_rows
                }
                if any(row["dims"] != 1536 for row in vector_rows):
                    raise RuntimeError("destination contains an embedding with the wrong dimension")
                if actual_vectors != source_vectors:
                    raise RuntimeError("embedding content verification failed")

                await conn.execute(
                    """INSERT INTO deployment_state(key, value, updated_at)
                       VALUES ('sqlite-import', 'verified', NOW())
                       ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()"""
                )

            return await _destination_counts(conn)
    finally:
        await pool.close()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="read-only SQLite snapshot")
    parser.add_argument(
        "--source-sha256",
        help="approved SHA-256 for the immutable standalone SQLite snapshot",
    )
    parser.add_argument(
        "--verify-only", action="store_true",
        help="validate source integrity and print counts without connecting to PostgreSQL",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if not args.verify_only and not args.source_sha256:
        raise SystemExit("--source-sha256 is required for migration")
    snapshot = read_sqlite_snapshot(args.source, args.source_sha256)
    validate_source_snapshot(snapshot)
    print("source integrity: ok")
    for table in BUSINESS_TABLES:
        print(f"source {table}: {snapshot.counts[table]}")
    if args.verify_only:
        return 0
    required = ("DB_HOST", "DB_NAME", "DB_USER", "DB_PASSWORD")
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        raise SystemExit("missing PostgreSQL configuration: " + ", ".join(missing))
    counts = asyncio.run(migrate(snapshot))
    for table in BUSINESS_TABLES:
        print(f"destination {table}: {counts[table]}")
    print("migration verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
