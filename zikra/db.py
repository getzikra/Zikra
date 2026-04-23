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
                m.access_count, m.confidence_score
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
                m.access_count, m.confidence_score
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
                        access_count, confidence_score
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
                        access_count, confidence_score
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
            'access_count': row['access_count'],
            'confidence_score': row['confidence_score'],
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
            'access_count': row['access_count'],
            'confidence_score': row['confidence_score'],
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
                m.access_count, m.confidence_score
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
                m.access_count, m.confidence_score
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
            'access_count': row['access_count'],
            'confidence_score': row['confidence_score'],
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
            'access_count': row['access_count'],
            'confidence_score': row['confidence_score'],
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
             "tags, resolution, access_count, created_at, updated_at")

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
                 julianday(COALESCE(m.updated_at, m.created_at))
                ) AS INTEGER
            ) AS days_idle,
            (SELECT COUNT(*) FROM memory_links l WHERE l.to_id = m.id) AS backlink_count
        FROM memories m
        WHERE m.project = ?
          AND (julianday('now') -
               julianday(COALESCE(m.updated_at, m.created_at))) > ?
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


async def record_run(data: dict, run_id: str) -> None:
    """Insert a prompt_run record."""
    if _is_pg:
        from zikra.db_postgres import log_run_pg, get_pg_pool
        await log_run_pg(get_pg_pool(), data, run_id)
        return

    await _aio_db.execute(
        """INSERT INTO prompt_runs
           (id, project, runner, prompt_id, prompt_name, status, output_summary,
            tokens_input, tokens_output, tokens_cache_read, tokens_cache_creation, cost_usd)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
        ]
    )
    await _aio_db.commit()


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


async def bump_access_count(memory_id: str) -> None:
    """Increment access_count for a memory."""
    if _is_pg:
        from zikra.db_postgres import bump_access_count_pg, get_pg_pool
        await bump_access_count_pg(get_pg_pool(), memory_id)
        return

    await _aio_db.execute(
        "UPDATE memories SET access_count = access_count + 1 WHERE id = ?",
        [memory_id]
    )
    await _aio_db.commit()


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


async def change_memory_type(memory_id: str, new_type: str) -> Optional[dict]:
    """Promote a requirement to a different memory_type. Returns the row or None."""
    if _is_pg:
        from zikra.db_postgres import change_memory_type_pg, get_pg_pool
        return await change_memory_type_pg(get_pg_pool(), memory_id, new_type)

    async with _aio_db.execute(
        "SELECT id, title FROM memories WHERE id = ? AND memory_type = 'requirement'",
        [memory_id]
    ) as cur:
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
                   access_count, created_by, pending_review, resolved, created_at
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
                   access_count, created_by, pending_review, resolved, created_at
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
