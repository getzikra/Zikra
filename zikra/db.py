import logging
import sqlite3
import sqlite_vec
import sys
import threading
import uuid
import json
import os
import re
import struct
from typing import Optional
from zikra.config import VECTOR_SEARCH_K

try:
    import aiosqlite
except ImportError:
    aiosqlite = None

logger = logging.getLogger(__name__)

# ── Backend state ──────────────────────────────────────────────────────────────
# _db / _lock: kept for auth.py which does a synchronous token lookup via
#              get_db_and_lock().  Do NOT use these in the async public API.
# _aio_db:     aiosqlite connection used by all async public functions so that
#              no blocking sqlite3 call stalls the event loop.

_db: Optional[sqlite3.Connection] = None
_lock = threading.Lock()
_aio_db: Optional['aiosqlite.Connection'] = None
_is_pg: bool = False


def new_id() -> str:
    return str(uuid.uuid4())


def is_postgres() -> bool:
    return _is_pg


def set_aio_db(conn: 'aiosqlite.Connection') -> None:
    """Called once from server.py lifespan after opening the aiosqlite connection."""
    global _aio_db
    _aio_db = conn


# ── SQLite internals (sync — for init_db / auth only) ─────────────────────────

def _make_connection(path: str) -> sqlite3.Connection:
    db = sqlite3.connect(path, check_same_thread=False)
    db.row_factory = sqlite3.Row
    try:
        db.enable_load_extension(True)
        sqlite_vec.load(db)
        db.enable_load_extension(False)
    except sqlite3.OperationalError as e:
        print(
            "\nERROR: Could not load the sqlite-vec extension.\n"
            "Your Python installation does not support SQLite extension loading.\n"
            "Fix: install Python from python.org or use 'brew install python' on macOS.\n"
            f"Detail: {e}",
            file=sys.stderr,
        )
        raise SystemExit(1)
    return db


def init_db() -> tuple:
    """Initialise the active backend.

    SQLite (default):  opens sync db, runs migrations, returns (db, lock).
    Postgres:          sets the _is_pg flag; actual async pool init is
                       done by server.py startup via db_postgres.init_pg().
                       Returns (None, None).

    Safe to call multiple times — skips setup if already initialised.
    """
    global _db, _is_pg
    backend = os.getenv('DB_BACKEND', 'sqlite').lower()

    if backend == 'postgres':
        _is_pg = True
        return None, None

    if _db is not None:   # already initialised (e.g. by __main__.py before uvicorn)
        return _db, _lock

    from zikra.migrate import run_migrations
    path = os.getenv('ZIKRA_DB_PATH', './zikra.db')
    _db = _make_connection(path)
    run_migrations(_db)
    return _db, _lock


def get_db_and_lock() -> tuple:
    """Return the raw SQLite (db, lock) — used by auth.py for sync token lookup."""
    return _db, _lock


# ── aiosqlite helpers ──────────────────────────────────────────────────────────

async def open_aio_db(path: str) -> 'aiosqlite.Connection':
    """Open an aiosqlite connection with WAL, foreign keys, and sqlite-vec loaded."""
    db = await aiosqlite.connect(path)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA foreign_keys=ON")
    await db.enable_load_extension(True)
    await db.load_extension(sqlite_vec.loadable_path())
    await db.enable_load_extension(False)
    return db


# ── SQLite async: save_memory ──────────────────────────────────────────────────

_WIKI_RE = re.compile(r'\[\[([^\[\]]+)\]\]')


def _extract_wikilinks(content_md: str) -> list:
    """Return unique [[title]] anchors found in content_md, preserving order."""
    if not content_md:
        return []
    seen = set()
    anchors = []
    for match in _WIKI_RE.findall(content_md):
        anchor = match.strip()
        if anchor and anchor not in seen:
            seen.add(anchor)
            anchors.append(anchor)
    return anchors


async def _store_wikilinks_sqlite(db: 'aiosqlite.Connection', from_id: str,
                                  content_md: str, project: str) -> None:
    """Replace from_id's rows in memory_links with edges parsed from content_md."""
    await db.execute("DELETE FROM memory_links WHERE from_id = ?", [from_id])
    anchors = _extract_wikilinks(content_md)
    if not anchors:
        return
    for anchor in anchors:
        async with db.execute(
            """SELECT id FROM memories
               WHERE title = ? AND (project = ? OR project = 'global')
               ORDER BY (project = ?) DESC LIMIT 1""",
            [anchor, project, project],
        ) as cur:
            row = await cur.fetchone()
        if not row:
            continue
        await db.execute(
            """INSERT OR IGNORE INTO memory_links(from_id, to_id, anchor)
               VALUES (?, ?, ?)""",
            [from_id, row['id'], anchor],
        )


async def _sqlite_save_memory(db: 'aiosqlite.Connection', data: dict, embedding: list) -> str:
    memory_id = new_id()
    vec_bytes = struct.pack(f'{len(embedding)}f', *embedding)

    await db.execute("""
        INSERT INTO memories
            (id, project, module, memory_type, title, content_md,
             tags, resolution, created_by, searchable, pending_review)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
        ON CONFLICT(title, memory_type, project) DO UPDATE SET
            content_md = excluded.content_md,
            tags = excluded.tags,
            pending_review = excluded.pending_review,
            updated_at = CURRENT_TIMESTAMP
    """, [
        memory_id,
        data.get('project', 'global'),
        data.get('module'),
        data.get('memory_type', 'conversation'),
        data.get('title', ''),
        data.get('content_md') or data.get('content', ''),
        json.dumps(data.get('tags', [])),
        data.get('resolution'),
        data.get('created_by'),
        data.get('pending_review', 0),
    ])

    async with db.execute(
        "SELECT rowid FROM memories WHERE title=? AND memory_type=? AND project=?",
        [data.get('title', ''), data.get('memory_type', 'conversation'), data.get('project', 'global')]
    ) as cur:
        row = await cur.fetchone()

    if row:
        rowid = row['rowid']
        await db.execute("DELETE FROM memories_vec WHERE rowid = ?", [rowid])
        await db.execute(
            "INSERT INTO memories_vec(rowid, embedding) VALUES (?, ?)",
            [rowid, vec_bytes]
        )
        await db.execute(
            "INSERT OR REPLACE INTO memories_fts(rowid, title, content_md) VALUES (?, ?, ?)",
            [rowid, data.get('title', ''), data.get('content_md') or data.get('content', '')]
        )

    async with db.execute(
        "SELECT id FROM memories WHERE title=? AND memory_type=? AND project=?",
        [data.get('title', ''), data.get('memory_type', 'conversation'), data.get('project', 'global')]
    ) as cur:
        row = await cur.fetchone()
    resolved_id = row['id'] if row else memory_id

    await _store_wikilinks_sqlite(
        db, resolved_id,
        data.get('content_md') or data.get('content', ''),
        data.get('project', 'global'),
    )

    # Pin state changes only when the caller explicitly sends 'pinned' —
    # a re-save without the field never silently unpins.
    if 'pinned' in data:
        await db.execute(
            "UPDATE memories SET pinned = ? WHERE id = ?",
            [1 if data['pinned'] else 0, resolved_id]
        )

    await db.commit()
    return resolved_id


# ── SQLite async: search_memories ─────────────────────────────────────────────

async def _fts_query(db: 'aiosqlite.Connection', match_expr: str, project: str, limit: int,
                    memory_type: str = None):
    """Run a single FTS5 MATCH query. Returns rows or raises."""
    # global → sees ALL memories; specific project → scoped to that project only
    if project == 'global':
        base_sql = """
            SELECT
                m.rowid, m.id, m.title,
                SUBSTR(m.content_md, 1, 500) AS snippet,
                m.memory_type, m.project, m.module,
                m.created_at, f.rank AS fts_score,
                m.access_count, m.confidence_score,
                m.pinned, m.last_accessed_at
            FROM memories m
            JOIN memories_fts f ON f.rowid = m.rowid
            WHERE memories_fts MATCH ?
              AND m.searchable = 1
        """
        params = [match_expr]
    else:
        base_sql = """
            SELECT
                m.rowid, m.id, m.title,
                SUBSTR(m.content_md, 1, 500) AS snippet,
                m.memory_type, m.project, m.module,
                m.created_at, f.rank AS fts_score,
                m.access_count, m.confidence_score,
                m.pinned, m.last_accessed_at
            FROM memories m
            JOIN memories_fts f ON f.rowid = m.rowid
            WHERE memories_fts MATCH ?
              AND m.searchable = 1
              AND m.project = ?
        """
        params = [match_expr, project]
    if memory_type:
        base_sql += "  AND m.memory_type = ?\n"
        params.append(memory_type)
    base_sql += "ORDER BY f.rank\nLIMIT ?"
    params.append(limit)
    async with db.execute(base_sql, params) as cur:
        return await cur.fetchall()


async def _fts_search(db: 'aiosqlite.Connection', query_text: str, project: str, limit: int,
                     memory_type: str = None) -> tuple:
    """Full-text search fallback — AND → OR → LIKE.
    Returns (results, degraded, reason)."""
    rows = []
    degraded = False
    reason = ''

    # Level 1 — FTS MATCH
    try:
        rows = await _fts_query(db, query_text, project, limit, memory_type=memory_type)
    except Exception as e:
        logger.warning(f'FTS MATCH failed: {e}')

    # Level 2 — OR token MATCH
    if not rows:
        tokens = [t for t in re.sub(r'[^\w\s]', ' ', query_text).split() if t]
        if len(tokens) > 1:
            try:
                rows = await _fts_query(db, ' OR '.join(tokens), project, limit, memory_type=memory_type)
                if rows:
                    degraded = True
                    reason = 'fts_or_fallback'
            except Exception as e:
                logger.warning(f'FTS OR fallback failed: {e}')

    # Level 3 — LIKE
    if not rows:
        try:
            # global → sees ALL memories; specific project → scoped to that project only
            if project == 'global':
                like_sql = """
                    SELECT
                        rowid, id, title,
                        SUBSTR(content_md, 1, 500) AS snippet,
                        memory_type, project, module, created_at,
                        -0.5 AS fts_score,
                        access_count, confidence_score,
                        pinned, last_accessed_at
                    FROM memories
                    WHERE (title LIKE ? OR content_md LIKE ?)
                      AND searchable = 1
                """
                like_params = [f'%{query_text}%', f'%{query_text}%']
            else:
                like_sql = """
                    SELECT
                        rowid, id, title,
                        SUBSTR(content_md, 1, 500) AS snippet,
                        memory_type, project, module, created_at,
                        -0.5 AS fts_score,
                        access_count, confidence_score,
                        pinned, last_accessed_at
                    FROM memories
                    WHERE (title LIKE ? OR content_md LIKE ?)
                      AND searchable = 1
                      AND project = ?
                """
                like_params = [f'%{query_text}%', f'%{query_text}%', project]
            if memory_type:
                like_sql += "  AND memory_type = ?\n"
                like_params.append(memory_type)
            like_sql += "LIMIT ?"
            like_params.append(limit)
            async with db.execute(like_sql, like_params) as cur:
                rows = await cur.fetchall()
            if rows:
                degraded = True
                reason = 'like_fallback'
        except Exception as e:
            logger.warning(f'LIKE fallback failed: {e}')
            return [], True, 'all_search_methods_failed'

    from zikra.scoring import score as rescore
    results = []
    for row in rows:
        fts = abs(float(row['fts_score']))
        raw = round(min(fts, 1.0), 4)
        mem = {
            'created_at': row['created_at'],
            'last_accessed_at': row['last_accessed_at'],
            'access_count': row['access_count'],
            'confidence_score': row['confidence_score'],
            'pinned': row['pinned'],
        }
        results.append({
            'id': row['id'],
            'title': row['title'],
            'snippet': row['snippet'] or '',
            'memory_type': row['memory_type'],
            'project': row['project'],
            'module': row['module'],
            'score': round(rescore(raw, mem), 4),
            'created_at': row['created_at'],
            'last_accessed_at': row['last_accessed_at'],
            'access_count': row['access_count'],
            'confidence_score': row['confidence_score'],
            'pinned': row['pinned'],
        })
    return results, degraded, reason


async def search_memories(db: 'aiosqlite.Connection', query_text: str, query_embedding: list,
                          project: str, limit: int = 5, memory_type: str = None) -> tuple:
    """Returns (results, degraded, reason)."""
    is_zero = all(v == 0.0 for v in query_embedding)

    vec_results = []
    if not is_zero:
        try:
            vec_bytes = struct.pack(f'{len(query_embedding)}f', *query_embedding)
            async with db.execute("""
                SELECT rowid, distance
                FROM memories_vec
                WHERE embedding MATCH ?
                  AND k = ?
            """, [vec_bytes, VECTOR_SEARCH_K]) as cur:
                vec_results = await cur.fetchall()
        except Exception as e:
            logger.warning(f'Vector search failed, falling back to FTS: {e}')
            vec_results = []

    if not vec_results:
        return await _fts_search(db, query_text, project, limit, memory_type=memory_type)

    rowid_to_distance = {row['rowid']: row['distance'] for row in vec_results}
    rowids = list(rowid_to_distance.keys())
    placeholders = ','.join('?' * len(rowids))

    # global → sees ALL memories; specific project → scoped to that project only
    if project == 'global':
        vec_sql = f"""
            SELECT
                m.rowid,
                m.id, m.title,
                SUBSTR(m.content_md, 1, 500) AS snippet,
                m.memory_type, m.project, m.module,
                m.created_at,
                COALESCE(f.rank, 0.0) AS fts_score,
                m.access_count, m.confidence_score,
                m.pinned, m.last_accessed_at
            FROM memories m
            LEFT JOIN (
                SELECT rowid, rank
                FROM memories_fts
                WHERE memories_fts MATCH ?
            ) f ON f.rowid = m.rowid
            WHERE m.rowid IN ({placeholders})
              AND m.searchable = 1
        """
        vec_params = [query_text] + rowids
    else:
        vec_sql = f"""
            SELECT
                m.rowid,
                m.id, m.title,
                SUBSTR(m.content_md, 1, 500) AS snippet,
                m.memory_type, m.project, m.module,
                m.created_at,
                COALESCE(f.rank, 0.0) AS fts_score,
                m.access_count, m.confidence_score,
                m.pinned, m.last_accessed_at
            FROM memories m
            LEFT JOIN (
                SELECT rowid, rank
                FROM memories_fts
                WHERE memories_fts MATCH ?
            ) f ON f.rowid = m.rowid
            WHERE m.rowid IN ({placeholders})
              AND m.searchable = 1
              AND m.project = ?
        """
        vec_params = [query_text] + rowids + [project]
    if memory_type:
        vec_sql += "  AND m.memory_type = ?\n"
        vec_params.append(memory_type)
    async with db.execute(vec_sql, vec_params) as cur:
        rows = await cur.fetchall()

    from zikra.scoring import score as rescore
    results = []
    for row in rows:
        distance = rowid_to_distance.get(row['rowid'], 1.0)
        cosine_sim = 1.0 - distance
        fts = abs(float(row['fts_score']))
        raw = round(0.7 * cosine_sim + 0.3 * min(fts, 1.0), 4)
        mem = {
            'created_at': row['created_at'],
            'last_accessed_at': row['last_accessed_at'],
            'access_count': row['access_count'],
            'confidence_score': row['confidence_score'],
            'pinned': row['pinned'],
        }
        results.append({
            'id': row['id'],
            'title': row['title'],
            'snippet': row['snippet'] or '',
            'memory_type': row['memory_type'],
            'project': row['project'],
            'module': row['module'],
            'score': round(rescore(raw, mem), 4),
            'created_at': row['created_at'],
            'last_accessed_at': row['last_accessed_at'],
            'access_count': row['access_count'],
            'confidence_score': row['confidence_score'],
            'pinned': row['pinned'],
        })

    results.sort(key=lambda x: x['score'], reverse=True)
    return results[:limit], False, ''


# ── Async public API — dispatches to SQLite or Postgres ───────────────────────
#
# Commands call these functions; they work transparently with both backends.
# SQLite path uses _aio_db (aiosqlite) — no blocking, no threading.

async def store_memory(data: dict, embedding: list) -> str:
    """Upsert a memory and its embedding."""
    if _is_pg:
        from zikra.db_postgres import save_memory_pg, get_pg_pool
        return await save_memory_pg(get_pg_pool(), data, embedding)
    return await _sqlite_save_memory(_aio_db, data, embedding)


async def nearest_projects(embedding: list, k: int) -> list[dict]:
    """Return nearest searchable memory projects across all projects."""
    if _is_pg:
        from zikra.db_postgres import nearest_projects_pg, get_pg_pool
        return await nearest_projects_pg(get_pg_pool(), embedding, k)

    vec_bytes = struct.pack(f'{len(embedding)}f', *embedding)
    async with _aio_db.execute("""
        SELECT m.project, 1.0 - v.distance AS sim
        FROM (
            SELECT rowid, distance
            FROM memories_vec
            WHERE embedding MATCH ?
              AND k = ?
        ) v
        JOIN memories m ON m.rowid = v.rowid
        WHERE m.searchable = 1
        ORDER BY v.distance
        LIMIT ?
    """, [vec_bytes, k, k]) as cur:
        rows = await cur.fetchall()
    return [{'project': row['project'], 'sim': float(row['sim'])} for row in rows]


async def find_recent_similar(created_by, project, memory_types: list,
                              window_min: int, embedding: list) -> Optional[dict]:
    """Find one recent similar memory for write-time deduplication."""
    if not created_by:
        return None
    if _is_pg:
        from zikra.db_postgres import find_recent_similar_pg, get_pg_pool
        return await find_recent_similar_pg(
            get_pg_pool(), created_by, project, memory_types, window_min, embedding
        )

    vec_bytes = struct.pack(f'{len(embedding)}f', *embedding)
    placeholders = ','.join('?' * len(memory_types))
    sql = f"""
        SELECT m.id, m.title, 1.0 - v.distance AS sim
        FROM (
            SELECT rowid, distance
            FROM memories_vec
            WHERE embedding MATCH ?
              AND k = ?
        ) v
        JOIN memories m ON m.rowid = v.rowid
        WHERE m.searchable = 1
          AND m.created_by = ?
          AND m.project = ?
          AND m.memory_type IN ({placeholders})
          AND m.created_at >= datetime('now', ?)
        ORDER BY v.distance
        LIMIT 1
    """
    params = [
        vec_bytes,
        VECTOR_SEARCH_K,
        created_by,
        project,
        *memory_types,
        f'-{window_min} minutes',
    ]
    async with _aio_db.execute(sql, params) as cur:
        row = await cur.fetchone()
    return {'id': row['id'], 'title': row['title'], 'sim': float(row['sim'])} if row else None


async def update_memory_content(memory_id: str, content_md: str, embedding: list) -> None:
    """Refresh an existing memory content and vector in place."""
    if _is_pg:
        from zikra.db_postgres import update_memory_content_pg, get_pg_pool
        await update_memory_content_pg(get_pg_pool(), memory_id, content_md, embedding)
        return

    vec_bytes = struct.pack(f'{len(embedding)}f', *embedding)
    async with _aio_db.execute(
        "SELECT rowid, title FROM memories WHERE id = ?",
        [memory_id],
    ) as cur:
        row = await cur.fetchone()
    if not row:
        return

    rowid = row['rowid']
    await _aio_db.execute(
        "UPDATE memories SET content_md = ?, updated_at = datetime('now') WHERE id = ?",
        [content_md, memory_id],
    )
    await _aio_db.execute("DELETE FROM memories_vec WHERE rowid = ?", [rowid])
    await _aio_db.execute(
        "INSERT INTO memories_vec(rowid, embedding) VALUES (?, ?)",
        [rowid, vec_bytes],
    )
    await _aio_db.execute(
        "INSERT OR REPLACE INTO memories_fts(rowid, title, content_md) VALUES (?, ?, ?)",
        [rowid, row['title'], content_md],
    )
    await _aio_db.commit()


async def find_memories(query_text: str, query_embedding: list,
                        project: str, limit: int, memory_type: str = None) -> tuple:
    """Hybrid vector + FTS search. Returns (results, degraded, reason)."""
    if _is_pg:
        from zikra.db_postgres import search_memories_pg, get_pg_pool
        return await search_memories_pg(get_pg_pool(), query_text, query_embedding, project, limit,
                                        memory_type=memory_type)
    return await search_memories(_aio_db, query_text, query_embedding, project, limit,
                                 memory_type=memory_type)


async def fetch_memory(memory_id: str = None, title: str = None,
                       memory_type: str = None, project: str = None) -> Optional[dict]:
    """Fetch a single memory by id or title, scoped to project when provided."""
    if _is_pg:
        from zikra.db_postgres import get_memory_pg, get_pg_pool
        return await get_memory_pg(get_pg_pool(), memory_id, title, memory_type, project)

    _COLS = ("id, title, content_md, memory_type, project, module, "
             "tags, resolution, access_count, created_at, updated_at, "
             "pinned, last_accessed_at, confidence_score")

    if memory_id:
        if project:
            sql = f"SELECT {_COLS} FROM memories WHERE id = ? AND project = ?"
            params = [memory_id, project]
        else:
            sql = f"SELECT {_COLS} FROM memories WHERE id = ?"
            params = [memory_id]
    elif memory_type:
        if project:
            sql = f"SELECT {_COLS} FROM memories WHERE title = ? AND memory_type = ? AND project = ?"
            params = [title, memory_type, project]
        else:
            sql = f"SELECT {_COLS} FROM memories WHERE title = ? AND memory_type = ?"
            params = [title, memory_type]
    else:
        if project:
            sql = f"SELECT {_COLS} FROM memories WHERE title = ? AND project = ? LIMIT 1"
            params = [title, project]
        else:
            sql = f"SELECT {_COLS} FROM memories WHERE title = ? LIMIT 1"
            params = [title]

    async with _aio_db.execute(sql, params) as cur:
        row = await cur.fetchone()
    return dict(row) if row else None


async def fetch_memory_links(memory_id: str) -> dict:
    """Return {links_out, links_in} for a memory. Each list item is
    {id, title, memory_type}. Missing memory → empty lists."""
    if not memory_id:
        return {'links_out': [], 'links_in': []}
    if _is_pg:
        from zikra.db_postgres import fetch_memory_links_pg, get_pg_pool
        return await fetch_memory_links_pg(get_pg_pool(), memory_id)

    async with _aio_db.execute(
        """SELECT m.id, m.title, m.memory_type
           FROM memory_links l JOIN memories m ON m.id = l.to_id
           WHERE l.from_id = ? ORDER BY m.title""",
        [memory_id],
    ) as cur:
        out_rows = await cur.fetchall()
    async with _aio_db.execute(
        """SELECT m.id, m.title, m.memory_type
           FROM memory_links l JOIN memories m ON m.id = l.from_id
           WHERE l.to_id = ? ORDER BY m.title""",
        [memory_id],
    ) as cur:
        in_rows = await cur.fetchall()
    return {
        'links_out': [dict(r) for r in out_rows],
        'links_in':  [dict(r) for r in in_rows],
    }


async def hygiene_report(project: str, stale_days: int) -> list:
    """Return memories idle for more than stale_days AND with zero incoming
    wikilinks. Each row has {id, title, memory_type, project, days_idle,
    access_count, backlink_count}. Sorted most-idle-first.
    """
    if _is_pg:
        from zikra.db_postgres import hygiene_report_pg, get_pg_pool
        return await hygiene_report_pg(get_pg_pool(), project, stale_days)

    async with _aio_db.execute(
        """
        SELECT
            m.id,
            m.title,
            m.memory_type,
            m.project,
            m.access_count,
            CAST(
                (julianday('now') -
                 julianday(COALESCE(m.last_accessed_at, m.updated_at, m.created_at))
                ) AS INTEGER
            ) AS days_idle,
            (SELECT COUNT(*) FROM memory_links l WHERE l.to_id = m.id) AS backlink_count
        FROM memories m
        WHERE m.project = ?
          AND COALESCE(m.pinned, 0) = 0
          AND (julianday('now') -
               julianday(COALESCE(m.last_accessed_at, m.updated_at, m.created_at))) > ?
          AND (SELECT COUNT(*) FROM memory_links l WHERE l.to_id = m.id) = 0
        ORDER BY days_idle DESC
        """,
        [project, stale_days],
    ) as cur:
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def fetch_links_between(memory_ids: list) -> list:
    """Return memory_links rows where both endpoints are in memory_ids.

    Used by the graph builder so wikilink edges can be rendered alongside the
    scored semantic edges. Each row is {from_id, to_id, anchor}.
    """
    if not memory_ids:
        return []
    if _is_pg:
        from zikra.db_postgres import fetch_links_between_pg, get_pg_pool
        return await fetch_links_between_pg(get_pg_pool(), memory_ids)

    placeholders = ','.join('?' * len(memory_ids))
    sql = (
        f"SELECT from_id, to_id, anchor FROM memory_links "
        f"WHERE from_id IN ({placeholders}) AND to_id IN ({placeholders})"
    )
    async with _aio_db.execute(sql, list(memory_ids) + list(memory_ids)) as cur:
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def record_run(data: dict, run_id: str) -> str:
    """Insert a prompt_run record. When session_id is present, upserts on
    (runner, session_id) so the Stop hook and the watcher daemon converge on
    ONE row per session instead of double-logging. Returns the row id."""
    if _is_pg:
        from zikra.db_postgres import log_run_pg, get_pg_pool
        return await log_run_pg(get_pg_pool(), data, run_id)

    await _aio_db.execute(
        """INSERT INTO prompt_runs
           (id, project, runner, prompt_id, prompt_name, status, output_summary,
            tokens_input, tokens_output, tokens_cache_read, tokens_cache_creation,
            cost_usd, session_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT (runner, session_id) WHERE session_id IS NOT NULL DO UPDATE SET
               project               = excluded.project,
               prompt_id             = COALESCE(excluded.prompt_id, prompt_runs.prompt_id),
               prompt_name           = COALESCE(excluded.prompt_name, prompt_runs.prompt_name),
               status                = excluded.status,
               output_summary        = CASE
                   WHEN LENGTH(COALESCE(excluded.output_summary, '')) > LENGTH(COALESCE(prompt_runs.output_summary, ''))
                   THEN excluded.output_summary ELSE prompt_runs.output_summary END,
               tokens_input          = MAX(COALESCE(excluded.tokens_input, 0), COALESCE(prompt_runs.tokens_input, 0)),
               tokens_output         = MAX(COALESCE(excluded.tokens_output, 0), COALESCE(prompt_runs.tokens_output, 0)),
               tokens_cache_read     = MAX(COALESCE(excluded.tokens_cache_read, 0), COALESCE(prompt_runs.tokens_cache_read, 0)),
               tokens_cache_creation = MAX(COALESCE(excluded.tokens_cache_creation, 0), COALESCE(prompt_runs.tokens_cache_creation, 0)),
               cost_usd              = COALESCE(excluded.cost_usd, prompt_runs.cost_usd)""",
        [
            run_id,
            data.get('project', 'global'),
            data.get('runner'),
            data.get('prompt_id'),
            data.get('prompt_name'),
            data.get('status', 'success'),
            data.get('output_summary'),
            data.get('tokens_input'),
            data.get('tokens_output'),
            data.get('tokens_cache_read'),
            data.get('tokens_cache_creation'),
            data.get('cost_usd'),
            data.get('session_id'),
        ]
    )
    await _aio_db.commit()

    session_id = data.get('session_id')
    if session_id and data.get('runner'):
        async with _aio_db.execute(
            "SELECT id FROM prompt_runs WHERE runner = ? AND session_id = ?",
            [data.get('runner'), session_id]
        ) as cur:
            row = await cur.fetchone()
        if row:
            return row['id']
    return run_id


async def create_ingest(data: dict, ingest_id: str) -> None:
    """Queue a transcript tail for server-side distillation."""
    if _is_pg:
        from zikra.db_postgres import create_ingest_pg, get_pg_pool
        await create_ingest_pg(get_pg_pool(), data, ingest_id)
        return
    await _aio_db.execute(
        """INSERT INTO session_ingests
           (id, runner, project, session_id, cwd, transcript_tail, status)
           VALUES (?, ?, ?, ?, ?, ?, 'pending')""",
        [
            ingest_id,
            data.get('runner'),
            data.get('project', 'global'),
            data.get('session_id'),
            data.get('cwd'),
            data.get('transcript_tail', ''),
        ]
    )
    await _aio_db.commit()


async def fetch_ingest(ingest_id: str) -> Optional[dict]:
    if _is_pg:
        from zikra.db_postgres import fetch_ingest_pg, get_pg_pool
        return await fetch_ingest_pg(get_pg_pool(), ingest_id)
    async with _aio_db.execute(
        "SELECT * FROM session_ingests WHERE id = ?", [ingest_id]
    ) as cur:
        row = await cur.fetchone()
    return dict(row) if row else None


async def finish_ingest(ingest_id: str, status: str, error: str = None,
                        memories_created: int = 0) -> None:
    if _is_pg:
        from zikra.db_postgres import finish_ingest_pg, get_pg_pool
        await finish_ingest_pg(get_pg_pool(), ingest_id, status, error, memories_created)
        return
    await _aio_db.execute(
        """UPDATE session_ingests
           SET status = ?, error = ?, memories_created = ?,
               distilled_at = datetime('now'),
               transcript_tail = CASE WHEN ? IN ('distilled', 'failed', 'skipped') THEN '' ELSE transcript_tail END
           WHERE id = ?""",
        [status, error, memories_created, status, ingest_id]
    )
    await _aio_db.commit()


async def list_pending_ingests(limit: int = 20) -> list:
    """Oldest-first pending ingests — drained on server startup."""
    if _is_pg:
        from zikra.db_postgres import list_pending_ingests_pg, get_pg_pool
        return await list_pending_ingests_pg(get_pg_pool(), limit)
    async with _aio_db.execute(
        "SELECT id FROM session_ingests WHERE status = 'pending' ORDER BY created_at LIMIT ?",
        [limit]
    ) as cur:
        rows = await cur.fetchall()
    return [r['id'] for r in rows]


async def record_pending_run(runner: str, prompt_id: str, project: str) -> None:
    """Record that `runner` just fetched `prompt_id`. UPSERT — last write wins.
    v1.0.6: server-side handshake, replaces the dead /tmp/zikra_prompt_id rendezvous."""
    if _is_pg:
        from zikra.db_postgres import record_pending_run_pg, get_pg_pool
        await record_pending_run_pg(get_pg_pool(), runner, prompt_id, project)
        return
    await _aio_db.execute("""
        INSERT INTO pending_runs (runner, project, prompt_id) VALUES (?, ?, ?)
        ON CONFLICT(runner, project) DO UPDATE SET
            prompt_id = excluded.prompt_id,
            created_at = datetime('now')
    """, [runner, project, prompt_id])
    await _aio_db.commit()


async def consume_pending_run(runner: str, project: str) -> Optional[str]:
    """Atomically read-and-delete the pending prompt_id for this (runner, project).
    Returns the prompt_id string or None if no pending handshake exists."""
    if _is_pg:
        from zikra.db_postgres import consume_pending_run_pg, get_pg_pool
        return await consume_pending_run_pg(get_pg_pool(), runner, project)
    async with _aio_db.execute(
        "SELECT prompt_id FROM pending_runs WHERE runner = ? AND project = ?",
        [runner, project]
    ) as cur:
        row = await cur.fetchone()
    if not row:
        return None
    await _aio_db.execute(
        "DELETE FROM pending_runs WHERE runner = ? AND project = ?",
        [runner, project]
    )
    await _aio_db.commit()
    return row['prompt_id']


async def list_runs(project: str = 'global', prompt_id: str = None,
                    prompt_name: str = None, limit: int = 100) -> list:
    """List prompt_runs rows joined with prompt title from memories."""
    if _is_pg:
        from zikra.db_postgres import list_runs_pg, get_pg_pool
        return await list_runs_pg(get_pg_pool(), project, prompt_id, prompt_name, limit)

    where = []
    params: list = []
    if project and project != 'global':
        where.append('r.project = ?'); params.append(project)
    if prompt_id:
        where.append('r.prompt_id = ?'); params.append(prompt_id)
    if prompt_name:
        where.append('r.prompt_name = ?'); params.append(prompt_name)
    where_sql = ('WHERE ' + ' AND '.join(where)) if where else ''
    params.append(limit)
    sql = f"""
        SELECT r.id, r.project, r.runner, r.prompt_id, r.prompt_name,
               r.status, r.output_summary,
               r.tokens_input, r.tokens_output,
               r.tokens_cache_read, r.tokens_cache_creation,
               r.cost_usd, r.created_at,
               m.title AS prompt_title
        FROM prompt_runs r
        LEFT JOIN memories m ON m.id = r.prompt_id
        {where_sql}
        ORDER BY r.created_at DESC
        LIMIT ?
    """
    async with _aio_db.execute(sql, params) as cur:
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def run_stats(project: str = 'global', prompt_id: str = None,
                    prompt_name: str = None) -> dict:
    """Aggregate token usage across prompt_runs (filterable)."""
    if _is_pg:
        from zikra.db_postgres import run_stats_pg, get_pg_pool
        return await run_stats_pg(get_pg_pool(), project, prompt_id, prompt_name)

    where = []
    params: list = []
    if project and project != 'global':
        where.append('project = ?'); params.append(project)
    if prompt_id:
        where.append('prompt_id = ?'); params.append(prompt_id)
    if prompt_name:
        where.append('prompt_name = ?'); params.append(prompt_name)
    where_sql = ('WHERE ' + ' AND '.join(where)) if where else ''
    sql = f"""
        SELECT COUNT(*) AS run_count,
               COALESCE(SUM(tokens_input),0)          AS sum_in,
               COALESCE(SUM(tokens_output),0)         AS sum_out,
               COALESCE(SUM(tokens_cache_read),0)     AS sum_cache_read,
               COALESCE(SUM(tokens_cache_creation),0) AS sum_cache_creation,
               COALESCE(AVG(tokens_input),0)          AS avg_in,
               COALESCE(AVG(tokens_output),0)         AS avg_out,
               COALESCE(AVG(tokens_cache_read),0)     AS avg_cache_read
        FROM prompt_runs
        {where_sql}
    """
    async with _aio_db.execute(sql, params) as cur:
        row = await cur.fetchone()
    return dict(row) if row else {}


async def update_memory_flags(memory_id: str, pinned: int = None,
                              searchable: int = None,
                              pending_review: int = None) -> bool:
    """Set pin/archive/review flags on a memory. Returns True if it existed."""
    sets, params = [], []
    if pinned is not None:
        sets.append('pinned = ?'); params.append(int(pinned))
    if searchable is not None:
        sets.append('searchable = ?'); params.append(int(searchable))
    if pending_review is not None:
        sets.append('pending_review = ?'); params.append(int(pending_review))
    if not sets:
        return False
    if _is_pg:
        from zikra.db_postgres import update_memory_flags_pg, get_pg_pool
        return await update_memory_flags_pg(get_pg_pool(), memory_id, pinned,
                                            searchable, pending_review)
    cur = await _aio_db.execute(
        f"UPDATE memories SET {', '.join(sets)}, updated_at = datetime('now') WHERE id = ?",
        params + [memory_id]
    )
    await _aio_db.commit()
    return cur.rowcount > 0


async def activity_stats(project: str = 'global', days: int = 30) -> dict:
    """Per-day activity for the dashboard: runs + tokens, memories created
    by type, errors. 'global' aggregates every project."""
    if _is_pg:
        from zikra.db_postgres import activity_stats_pg, get_pg_pool
        return await activity_stats_pg(get_pg_pool(), project, days)

    scope_runs, scope_mems, scope_errs = '', '', ''
    params: list = []
    if project and project != 'global':
        scope_runs = 'AND project = ?'
        scope_mems = 'AND project = ?'
        scope_errs = 'AND project = ?'
        params = [project]
    since = f'-{int(days)} days'

    async with _aio_db.execute(
        f"""SELECT DATE(created_at) AS d, COUNT(*) AS n,
                   COALESCE(SUM(tokens_input),0) AS tokens_in,
                   COALESCE(SUM(tokens_output),0) AS tokens_out,
                   COALESCE(SUM(tokens_cache_read),0) AS tokens_cache
            FROM prompt_runs
            WHERE created_at >= datetime('now', ?) {scope_runs}
            GROUP BY DATE(created_at) ORDER BY d""",
        [since] + params
    ) as cur:
        runs = [dict(r) for r in await cur.fetchall()]

    async with _aio_db.execute(
        f"""SELECT DATE(created_at) AS d, memory_type, COUNT(*) AS n
            FROM memories
            WHERE created_at >= datetime('now', ?) {scope_mems}
            GROUP BY DATE(created_at), memory_type ORDER BY d""",
        [since] + params
    ) as cur:
        memories = [dict(r) for r in await cur.fetchall()]

    async with _aio_db.execute(
        f"""SELECT DATE(created_at) AS d, COUNT(*) AS n
            FROM error_log
            WHERE created_at >= datetime('now', ?) {scope_errs}
            GROUP BY DATE(created_at) ORDER BY d""",
        [since] + params
    ) as cur:
        errors = [dict(r) for r in await cur.fetchall()]

    return {'runs': runs, 'memories': memories, 'errors': errors, 'days': days}


async def recent_memories(project: str = 'global', limit: int = 20) -> list:
    """Latest memories by creation time — the dashboard 'today feed'."""
    if _is_pg:
        from zikra.db_postgres import recent_memories_pg, get_pg_pool
        return await recent_memories_pg(get_pg_pool(), project, limit)
    scope = '' if project == 'global' else 'AND project = ?'
    params = [] if project == 'global' else [project]
    async with _aio_db.execute(
        f"""SELECT id, title, SUBSTR(content_md, 1, 280) AS snippet, memory_type,
                   project, created_by, pending_review, pinned, created_at
            FROM memories WHERE searchable = 1 {scope}
            ORDER BY created_at DESC LIMIT ?""",
        params + [limit]
    ) as cur:
        return [dict(r) for r in await cur.fetchall()]


async def recent_errors(project: str = 'global', limit: int = 20) -> list:
    """Latest error_log rows — surfaced in the dashboard Activity tab."""
    if _is_pg:
        from zikra.db_postgres import recent_errors_pg, get_pg_pool
        return await recent_errors_pg(get_pg_pool(), project, limit)
    scope = '' if project == 'global' else 'WHERE project = ?'
    params = [] if project == 'global' else [project]
    async with _aio_db.execute(
        f"""SELECT id, project, runner, error_type, message,
                   SUBSTR(context_md, 1, 500) AS context_md, created_at
            FROM error_log {scope}
            ORDER BY created_at DESC LIMIT ?""",
        params + [limit]
    ) as cur:
        return [dict(r) for r in await cur.fetchall()]


async def list_consolidation_candidates(project: str, min_age_days: int,
                                        limit: int = 200) -> list:
    """Old, unpinned conversation/diary memories eligible for consolidation."""
    if _is_pg:
        from zikra.db_postgres import list_consolidation_candidates_pg, get_pg_pool
        return await list_consolidation_candidates_pg(get_pg_pool(), project, min_age_days, limit)
    async with _aio_db.execute(
        """SELECT id, title, content_md, created_at FROM memories
           WHERE project = ?
             AND memory_type IN ('conversation', 'diary')
             AND searchable = 1
             AND COALESCE(pinned, 0) = 0
             AND created_at < datetime('now', ?)
           ORDER BY created_at
           LIMIT ?""",
        [project, f'-{int(min_age_days)} days', limit]
    ) as cur:
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def archive_memories(memory_ids: list, note: str) -> None:
    """Archive memories (searchable=0) with a resolution note. Reversible."""
    if not memory_ids:
        return
    if _is_pg:
        from zikra.db_postgres import archive_memories_pg, get_pg_pool
        await archive_memories_pg(get_pg_pool(), memory_ids, note)
        return
    placeholders = ','.join('?' * len(memory_ids))
    await _aio_db.execute(
        f"UPDATE memories SET searchable = 0, resolution = ?, "
        f"updated_at = datetime('now') WHERE id IN ({placeholders})",
        [note] + list(memory_ids)
    )
    await _aio_db.commit()


async def count_recent_errors(project: str, error_type: str, message: str,
                              days: int = 7) -> int:
    """How often this exact error has been logged recently — used to promote
    recurring errors into searchable bug memories."""
    if _is_pg:
        from zikra.db_postgres import count_recent_errors_pg, get_pg_pool
        return await count_recent_errors_pg(get_pg_pool(), project, error_type, message, days)
    async with _aio_db.execute(
        """SELECT COUNT(*) AS n FROM error_log
           WHERE project = ? AND COALESCE(error_type,'') = COALESCE(?,'')
             AND message = ?
             AND created_at >= datetime('now', ?)""",
        [project, error_type, message, f'-{int(days)} days']
    ) as cur:
        row = await cur.fetchone()
    return row['n'] if row else 0


async def record_error(data: dict, error_id: str) -> None:
    """Insert an error_log record."""
    if _is_pg:
        from zikra.db_postgres import log_error_pg, get_pg_pool
        await log_error_pg(get_pg_pool(), data, error_id)
        return

    await _aio_db.execute(
        """INSERT INTO error_log
           (id, project, runner, error_type, message, stack_trace, context_md)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        [
            error_id,
            data.get('project', 'global'),
            data.get('runner'),
            data.get('error_type'),
            data.get('message') or data.get('error', ''),
            data.get('stack_trace'),
            data.get('context_md'),
        ]
    )
    await _aio_db.commit()


async def get_schema_info() -> dict:
    """Return schema info for the active backend."""
    if _is_pg:
        from zikra.db_postgres import get_schema_pg, get_pg_pool
        return await get_schema_pg(get_pg_pool())

    async with _aio_db.execute(
        "SELECT name, sql FROM sqlite_master "
        "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ) as cur:
        tables = await cur.fetchall()
    schema = {t['name']: t['sql'] for t in tables if t['sql']}
    return {
        'engine': 'sqlite3 + sqlite-vec (aiosqlite)',
        'tables': list(schema.keys()),
        'schema': schema,
    }


async def fetch_prompt_row(prompt_name: str, project: str = None) -> Optional[dict]:
    """Fetch a prompt memory by title, scoped to project when provided."""
    if _is_pg:
        from zikra.db_postgres import get_prompt_pg, get_pg_pool
        return await get_prompt_pg(get_pg_pool(), prompt_name, project)

    if project:
        sql = ("SELECT id, title, content_md, project, access_count, created_at "
               "FROM memories WHERE title = ? AND memory_type = 'prompt' AND project = ?")
        params = [prompt_name, project]
    else:
        sql = ("SELECT id, title, content_md, project, access_count, created_at "
               "FROM memories WHERE title = ? AND memory_type = 'prompt'")
        params = [prompt_name]

    async with _aio_db.execute(sql, params) as cur:
        row = await cur.fetchone()
    return dict(row) if row else None


async def delete_memory(memory_id: str) -> Optional[dict]:
    """Delete a memory by UUID. Returns {id, title, ...} on success, None if not found."""
    if _is_pg:
        from zikra.db_postgres import delete_memory_pg, get_pg_pool
        return await delete_memory_pg(get_pg_pool(), memory_id)

    async with _aio_db.execute(
        "SELECT rowid, id, title, memory_type, project FROM memories WHERE id = ?",
        [memory_id],
    ) as cur:
        row = await cur.fetchone()
    if not row:
        return None
    rowid = row['rowid']
    await _aio_db.execute("DELETE FROM memories WHERE id = ?", [memory_id])
    try:
        await _aio_db.execute("DELETE FROM memories_vec WHERE rowid = ?", [rowid])
    except Exception:
        pass
    try:
        await _aio_db.execute("DELETE FROM memories_fts WHERE rowid = ?", [rowid])
    except Exception:
        pass
    await _aio_db.commit()
    return {
        'id': row['id'],
        'title': row['title'],
        'memory_type': row['memory_type'],
        'project': row['project'],
    }


async def log_retrievals(memory_ids: list, source: str, query: str = None) -> None:
    """Record that memories were retrieved: bump access_count, refresh
    last_accessed_at (resets the decay clock), and append retrievals rows.
    source is 'search', 'get', or 'context'. Never raises — retrieval
    logging must not break the read path."""
    memory_ids = [m for m in (memory_ids or []) if m]
    if not memory_ids:
        return
    try:
        if _is_pg:
            from zikra.db_postgres import log_retrievals_pg, get_pg_pool
            await log_retrievals_pg(get_pg_pool(), memory_ids, source, query)
            return

        placeholders = ','.join('?' * len(memory_ids))
        await _aio_db.execute(
            f"UPDATE memories SET access_count = access_count + 1, "
            f"last_accessed_at = datetime('now') WHERE id IN ({placeholders})",
            memory_ids
        )
        await _aio_db.executemany(
            "INSERT INTO retrievals (id, memory_id, source, query) VALUES (?, ?, ?, ?)",
            [[new_id(), mid, source, query] for mid in memory_ids]
        )
        await _aio_db.commit()
    except Exception:
        logger.exception('retrieval logging failed')


async def bump_access_count(memory_id: str) -> None:
    """Increment access_count for a memory (explicit fetch)."""
    await log_retrievals([memory_id], 'get')


async def add_token(token_id: str, token: str, person_name: str, role: str,
                    project_scope: str = None) -> None:
    """Insert a new access token."""
    if _is_pg:
        from zikra.db_postgres import add_token_pg, get_pg_pool
        await add_token_pg(get_pg_pool(), token_id, token, person_name, role, project_scope)
        return

    await _aio_db.execute(
        "INSERT INTO access_tokens (id, token, person_name, role, active, project_scope) VALUES (?, ?, ?, ?, 1, ?)",
        [token_id, token, person_name, role, project_scope]
    )
    await _aio_db.commit()


async def log_token_hit(label: str, command: str) -> None:
    if _is_pg:
        from zikra.db_postgres import log_token_hit_pg, get_pg_pool
        await log_token_hit_pg(get_pg_pool(), label, command)
        return
    await _aio_db.execute(
        "INSERT INTO token_hits (id, label, command) VALUES (?, ?, ?)",
        [new_id(), label, command]
    )
    await _aio_db.commit()


async def token_usage_stats() -> list:
    if _is_pg:
        from zikra.db_postgres import token_usage_stats_pg, get_pg_pool
        return await token_usage_stats_pg(get_pg_pool())
    async with _aio_db.execute("""
        SELECT label,
               COUNT(*)                                              AS hits_total,
               COUNT(CASE WHEN ts > datetime('now','-7 days') THEN 1 END) AS hits_7d,
               COUNT(CASE WHEN ts > datetime('now','-1 day')  THEN 1 END) AS hits_24h,
               MAX(ts)                                               AS last_seen
        FROM token_hits
        GROUP BY label
        ORDER BY hits_total DESC
    """) as cur:
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def list_token_labels() -> list:
    """Return person_name for all active non-owner tokens, ordered by creation."""
    if _is_pg:
        from zikra.db_postgres import list_token_labels_pg, get_pg_pool
        return await list_token_labels_pg(get_pg_pool())

    async with _aio_db.execute(
        "SELECT person_name FROM access_tokens WHERE active = 1 AND role != 'owner' ORDER BY created_at"
    ) as cur:
        rows = await cur.fetchall()
    return [r[0] for r in rows if r[0]]


async def list_by_memory_type(memory_type: str, project: str, limit: int,
                              pending_review: Optional[int] = None,
                              status: str = None) -> list:
    """List memories filtered by type and project.
    status='pending'|'resolved' maps to pending_review filter.
    pending_review=1 filters to pending only (legacy param, still accepted).
    Default (no status, no pending_review): return all."""
    if _is_pg:
        from zikra.db_postgres import list_by_type_pg, get_pg_pool
        return await list_by_type_pg(get_pg_pool(), memory_type, project, limit, pending_review, status)

    # Map status string to pending_review value
    if status is not None and pending_review is None:
        if status == 'pending':
            pending_review = 1
        elif status == 'resolved':
            pending_review = 0

    # global → sees ALL memories; specific project → scoped to that project only
    if pending_review is not None:
        if project == 'global':
            sql = """
                SELECT id, title, SUBSTR(content_md, 1, 300) AS snippet,
                       project, access_count, created_by, created_at
                FROM memories
                WHERE memory_type = ?
                  AND pending_review = ?
                ORDER BY access_count DESC, created_at DESC
                LIMIT ?
            """
            params = [memory_type, pending_review, limit]
        else:
            sql = """
                SELECT id, title, SUBSTR(content_md, 1, 300) AS snippet,
                       project, access_count, created_by, created_at
                FROM memories
                WHERE memory_type = ?
                  AND project = ?
                  AND pending_review = ?
                ORDER BY access_count DESC, created_at DESC
                LIMIT ?
            """
            params = [memory_type, project, pending_review, limit]
    else:
        if project == 'global':
            sql = """
                SELECT id, title, SUBSTR(content_md, 1, 300) AS snippet,
                       project, access_count, created_by, created_at
                FROM memories
                WHERE memory_type = ?
                ORDER BY access_count DESC, created_at DESC
                LIMIT ?
            """
            params = [memory_type, limit]
        else:
            sql = """
                SELECT id, title, SUBSTR(content_md, 1, 300) AS snippet,
                       project, access_count, created_by, created_at
                FROM memories
                WHERE memory_type = ?
                  AND project = ?
                ORDER BY access_count DESC, created_at DESC
                LIMIT ?
            """
            params = [memory_type, project, limit]

    async with _aio_db.execute(sql, params) as cur:
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def change_memory_type(memory_id: str, new_type: str,
                             from_type: str = None) -> Optional[dict]:
    """Change a memory's type (e.g. promote a requirement or a diary to a
    decision). When from_type is given, only a memory of that type matches —
    promote_requirement uses this guard. Returns the row or None."""
    if _is_pg:
        from zikra.db_postgres import change_memory_type_pg, get_pg_pool
        return await change_memory_type_pg(get_pg_pool(), memory_id, new_type, from_type)

    if from_type:
        sql = "SELECT id, title FROM memories WHERE id = ? AND memory_type = ?"
        params = [memory_id, from_type]
    else:
        sql = "SELECT id, title FROM memories WHERE id = ?"
        params = [memory_id]
    async with _aio_db.execute(sql, params) as cur:
        row = await cur.fetchone()
    if not row:
        return None
    await _aio_db.execute("""
        UPDATE memories
        SET memory_type = ?, pending_review = 0, updated_at = datetime('now')
        WHERE id = ?
    """, [new_type, memory_id])
    await _aio_db.commit()
    return dict(row) if row else None


async def list_memory_types() -> list[str]:
    """Distinct memory types in use — feeds the dashboard type filter."""
    if _is_pg:
        from zikra.db_postgres import list_memory_types_pg, get_pg_pool
        return await list_memory_types_pg(get_pg_pool())
    async with _aio_db.execute(
        "SELECT DISTINCT memory_type FROM memories WHERE memory_type IS NOT NULL ORDER BY memory_type"
    ) as cur:
        rows = await cur.fetchall()
    return [r['memory_type'] for r in rows]


async def list_projects() -> list[str]:
    """Return distinct project names."""
    if _is_pg:
        from zikra.db_postgres import list_projects_pg, get_pg_pool
        return await list_projects_pg(get_pg_pool())

    async with _aio_db.execute("""
        SELECT DISTINCT project
        FROM memories
        WHERE project IS NOT NULL AND project != ''
        ORDER BY project
    """) as cur:
        rows = await cur.fetchall()
    return [r['project'] for r in rows]


async def list_all_memories(project: str = 'global', limit: int = 250) -> list[dict]:
    """Return a compact list of memories for UI views such as graph browsing."""
    if _is_pg:
        from zikra.db_postgres import list_all_memories_pg, get_pg_pool
        return await list_all_memories_pg(get_pg_pool(), project, limit)

    if project == 'global':
        sql = """
            SELECT id, title, SUBSTR(content_md, 1, 280) AS snippet,
                   content_md, memory_type, project, module, tags,
                   access_count, created_by, pending_review, resolved, created_at,
                   pinned, last_accessed_at, confidence_score
            FROM memories
            WHERE searchable = 1
            ORDER BY access_count DESC, created_at DESC
            LIMIT ?
        """
        params = [limit]
    else:
        sql = """
            SELECT id, title, SUBSTR(content_md, 1, 280) AS snippet,
                   content_md, memory_type, project, module, tags,
                   access_count, created_by, pending_review, resolved, created_at,
                   pinned, last_accessed_at, confidence_score
            FROM memories
            WHERE searchable = 1
              AND project = ?
            ORDER BY access_count DESC, created_at DESC
            LIMIT ?
        """
        params = [project, limit]

    async with _aio_db.execute(sql, params) as cur:
        rows = await cur.fetchall()

    out = []
    for row in rows:
        item = dict(row)
        try:
            item['tags'] = json.loads(item.get('tags') or '[]')
        except (TypeError, json.JSONDecodeError):
            item['tags'] = []
        out.append(item)
    return out


async def count_memories_by_project(project: str) -> int:
    """Return memory count scoped by project. 'global' sees all."""
    if _is_pg:
        from zikra.db_postgres import count_memories_pg, get_pg_pool
        return await count_memories_pg(get_pg_pool(), project)
    if project == 'global':
        sql = "SELECT COUNT(*) FROM memories WHERE searchable = 1"
        params = ()
    else:
        sql = "SELECT COUNT(*) FROM memories WHERE searchable = 1 AND project = ?"
        params = (project,)
    async with _aio_db.execute(sql, params) as cur:
        row = await cur.fetchone()
    return row[0] if row else 0


async def debug_memory_count() -> int:
    """Return total count of memories (for debug_protocol)."""
    if _is_pg:
        from zikra.db_postgres import debug_count_pg, get_pg_pool
        return await debug_count_pg(get_pg_pool())

    async with _aio_db.execute('SELECT COUNT(*) FROM memories') as cur:
        row = await cur.fetchone()
    return row[0] if row else 0
