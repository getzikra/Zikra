"""PostgreSQL backend for zikra-lite using asyncpg + pgvector.

Activated when DB_BACKEND=postgres. Requires:
  - PostgreSQL with pgvector extension
  - asyncpg Python package  (pip install asyncpg)

Env vars:
  DB_HOST      (default: localhost)
  DB_PORT      (default: 5432)
  DB_NAME      (default: zikra)
  DB_USER      (default: postgres)
  DB_PASSWORD  (default: '')
"""

import json
import logging
import os
from typing import Optional

from zikra.config import VECTOR_SEARCH_K
from zikra.scoring import score as rescore

logger = logging.getLogger(__name__)

_pg_pool: Optional['asyncpg.Pool'] = None

# ── Schema DDL ────────────────────────────────────────────────────────────────

_PG_TABLES = """
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS memories (
    id           TEXT PRIMARY KEY,
    project      TEXT NOT NULL DEFAULT 'global',
    module       TEXT,
    memory_type  TEXT NOT NULL DEFAULT 'conversation',
    title        TEXT NOT NULL,
    content_md   TEXT NOT NULL DEFAULT '',
    tags         TEXT NOT NULL DEFAULT '[]',
    resolution   TEXT,
    created_by   TEXT,
    confidence_score REAL    DEFAULT 1.0,
    access_count     INTEGER DEFAULT 0,
    searchable       INTEGER DEFAULT 1,
    resolved         INTEGER DEFAULT 0,
    pending_review   INTEGER DEFAULT 0,
    created_at   TIMESTAMPTZ DEFAULT NOW(),
    updated_at   TIMESTAMPTZ DEFAULT NOW(),
    embedding    halfvec(3072),
    UNIQUE (title, memory_type, project)
);

CREATE INDEX IF NOT EXISTS idx_memories_project
    ON memories(project, memory_type);

CREATE TABLE IF NOT EXISTS prompt_runs (
    id             TEXT PRIMARY KEY,
    project        TEXT,
    runner         TEXT,
    prompt_name    TEXT,
    status         TEXT DEFAULT 'success',
    output_summary TEXT,
    tokens_input   INTEGER,
    tokens_output  INTEGER,
    cost_usd       REAL,
    created_at     TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS error_log (
    id          TEXT PRIMARY KEY,
    project     TEXT,
    runner      TEXT,
    error_type  TEXT,
    message     TEXT,
    stack_trace TEXT,
    context_md  TEXT,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS access_tokens (
    id          TEXT PRIMARY KEY,
    token       TEXT NOT NULL UNIQUE,
    person_name TEXT,
    role        TEXT DEFAULT 'owner',
    active      INTEGER DEFAULT 1,
    token_name  TEXT,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);
"""

# Separate so a missing pgvector extension doesn't break table creation
_PG_VEC_INDEX = """
CREATE INDEX IF NOT EXISTS idx_memories_embedding
ON memories USING hnsw (embedding halfvec_cosine_ops);
"""


# ── Helpers ───────────────────────────────────────────────────────────────────

def _vec_str(embedding: list) -> Optional[str]:
    """Convert embedding list → pgvector literal '[f1,f2,...]', or None if all zeros."""
    if not embedding or all(v == 0.0 for v in embedding):
        return None
    return '[' + ','.join(repr(float(v)) for v in embedding) + ']'


def _iso(ts) -> str:
    """Return an ISO-format string regardless of whether ts is a str or datetime."""
    if ts is None:
        return ''
    if isinstance(ts, str):
        return ts
    return ts.isoformat()


def _row_to_dict(row) -> dict:
    """asyncpg Record → plain dict with ISO timestamp strings."""
    d = dict(row)
    for k in ('created_at', 'updated_at'):
        if k in d:
            d[k] = _iso(d[k])
    return d


# ── Pool lifecycle ─────────────────────────────────────────────────────────────

async def init_pg() -> 'asyncpg.Pool':
    """Create the asyncpg connection pool and apply schema migrations."""
    global _pg_pool
    try:
        import asyncpg
    except ImportError:
        raise RuntimeError(
            "asyncpg is required for Postgres mode.\n"
            "Run: pip install asyncpg"
        )

    host = os.getenv('DB_HOST', 'localhost')
    port = int(os.getenv('DB_PORT', '5432'))
    dbname = os.getenv('DB_NAME', 'zikra')
    user = os.getenv('DB_USER', 'zikra')
    password = os.getenv('DB_PASSWORD', '')

    _pg_pool = await asyncpg.create_pool(
        host=host, port=port, database=dbname,
        user=user, password=password,
        min_size=1, max_size=10,
    )

    async with _pg_pool.acquire() as conn:
        await conn.execute(_PG_TABLES)
        try:
            await conn.execute(_PG_VEC_INDEX)
        except Exception as e:
            logger.warning(f'Vector index creation skipped, falling back to FTS: {e}')

    return _pg_pool


def get_pg_pool() -> Optional['asyncpg.Pool']:
    return _pg_pool


# ── save_memory ───────────────────────────────────────────────────────────────

async def save_memory_pg(pool: 'asyncpg.Pool', data: dict, embedding: list) -> str:
    from zikra.db import new_id
    memory_id = new_id()
    vec = _vec_str(embedding)

    async with pool.acquire() as conn:
        pending_review = data.get('pending_review', 0)
        if vec is not None:
            row = await conn.fetchrow("""
                INSERT INTO memories
                    (id, project, module, memory_type, title, content_md,
                     tags, resolution, created_by, searchable, pending_review, embedding)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,1,$10,$11::halfvec)
                ON CONFLICT (title, memory_type, project) DO UPDATE SET
                    content_md     = EXCLUDED.content_md,
                    tags           = EXCLUDED.tags,
                    embedding      = EXCLUDED.embedding,
                    pending_review = EXCLUDED.pending_review,
                    updated_at     = NOW()
                RETURNING id
            """,
                memory_id,
                data.get('project', 'global'),
                data.get('module'),
                data.get('memory_type', 'conversation'),
                data.get('title', ''),
                data.get('content_md') or data.get('content', ''),
                json.dumps(data.get('tags', [])),
                data.get('resolution'),
                data.get('created_by'),
                pending_review,
                vec,
            )
        else:
            row = await conn.fetchrow("""
                INSERT INTO memories
                    (id, project, module, memory_type, title, content_md,
                     tags, resolution, created_by, searchable, pending_review)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,1,$10)
                ON CONFLICT (title, memory_type, project) DO UPDATE SET
                    content_md     = EXCLUDED.content_md,
                    tags           = EXCLUDED.tags,
                    pending_review = EXCLUDED.pending_review,
                    updated_at     = NOW()
                RETURNING id
            """,
                memory_id,
                data.get('project', 'global'),
                data.get('module'),
                data.get('memory_type', 'conversation'),
                data.get('title', ''),
                data.get('content_md') or data.get('content', ''),
                json.dumps(data.get('tags', [])),
                data.get('resolution'),
                data.get('created_by'),
                pending_review,
            )

    return row['id'] if row else memory_id


# ── search_memories ───────────────────────────────────────────────────────────

async def _fts_search_pg(conn, query_text: str, project: str, limit: int,
                        memory_type: str = None) -> tuple:
    """tsvector FTS with ILIKE fallback. Returns (results, degraded, reason)."""
    # global → sees ALL memories; specific project → scoped to that project only
    project_param = None if project == 'global' else project
    rows = []
    degraded = False
    reason = ''

    # Level 1 — tsvector FTS MATCH
    try:
        if memory_type:
            rows = await conn.fetch("""
                SELECT id, title,
                       SUBSTRING(content_md, 1, 500)  AS snippet,
                       memory_type, project, module,
                       created_at, access_count, confidence_score,
                       ts_rank(
                           to_tsvector('english', title || ' ' || content_md),
                           plainto_tsquery('english', $1)
                       ) AS fts_score
                FROM memories
                WHERE to_tsvector('english', title || ' ' || content_md)
                          @@ plainto_tsquery('english', $1)
                  AND searchable = 1
                  AND ($2::text IS NULL OR project = $2)
                  AND memory_type = $4
                ORDER BY fts_score DESC
                LIMIT $3
            """, query_text, project_param, limit, memory_type)
        else:
            rows = await conn.fetch("""
                SELECT id, title,
                       SUBSTRING(content_md, 1, 500)  AS snippet,
                       memory_type, project, module,
                       created_at, access_count, confidence_score,
                       ts_rank(
                           to_tsvector('english', title || ' ' || content_md),
                           plainto_tsquery('english', $1)
                       ) AS fts_score
                FROM memories
                WHERE to_tsvector('english', title || ' ' || content_md)
                          @@ plainto_tsquery('english', $1)
                  AND searchable = 1
                  AND ($2::text IS NULL OR project = $2)
                ORDER BY fts_score DESC
                LIMIT $3
            """, query_text, project_param, limit)
    except Exception as e:
        logger.warning(f'FTS MATCH failed: {e}')

    # Level 2 — ILIKE fallback
    if not rows:
        try:
            if memory_type:
                rows = await conn.fetch("""
                    SELECT id, title,
                           SUBSTRING(content_md, 1, 500) AS snippet,
                           memory_type, project, module,
                           created_at, access_count, confidence_score,
                           0.5::float AS fts_score
                    FROM memories
                    WHERE (title ILIKE $1 OR content_md ILIKE $1)
                      AND searchable = 1
                      AND ($2::text IS NULL OR project = $2)
                      AND memory_type = $4
                    LIMIT $3
                """, f'%{query_text}%', project_param, limit, memory_type)
            else:
                rows = await conn.fetch("""
                    SELECT id, title,
                           SUBSTRING(content_md, 1, 500) AS snippet,
                           memory_type, project, module,
                           created_at, access_count, confidence_score,
                           0.5::float AS fts_score
                    FROM memories
                    WHERE (title ILIKE $1 OR content_md ILIKE $1)
                      AND searchable = 1
                      AND ($2::text IS NULL OR project = $2)
                    LIMIT $3
                """, f'%{query_text}%', project_param, limit)
            if rows:
                degraded = True
                reason = 'like_fallback'
        except Exception as e:
            logger.warning(f'LIKE fallback failed: {e}')
            return [], True, 'all_search_methods_failed'

    results = []
    for row in rows:
        raw = round(min(float(row['fts_score']), 1.0), 4)
        created_str = _iso(row['created_at'])
        mem = {
            'created_at': created_str,
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
            'created_at': created_str,
        })
    return results, degraded, reason


async def search_memories_pg(pool: 'asyncpg.Pool', query_text: str,
                              query_embedding: list, project: str, limit: int,
                              memory_type: str = None) -> tuple:
    """Returns (results, degraded, reason)."""
    is_zero = not query_embedding or all(v == 0.0 for v in query_embedding)
    vec = None if is_zero else _vec_str(query_embedding)
    # global → sees ALL memories; specific project → scoped to that project only
    project_param = None if project == 'global' else project

    async with pool.acquire() as conn:
        if vec is None:
            return await _fts_search_pg(conn, query_text, project, limit, memory_type=memory_type)

        # Vector search — top K candidates
        try:
            if memory_type:
                vec_rows = await conn.fetch("""
                    SELECT id,
                           1.0 - (embedding <=> $1::halfvec) AS cosine_sim
                    FROM memories
                    WHERE embedding IS NOT NULL
                      AND searchable = 1
                      AND ($2::text IS NULL OR project = $2)
                      AND memory_type = $4
                    ORDER BY embedding <=> $1::halfvec
                    LIMIT $3
                """, vec, project_param, VECTOR_SEARCH_K, memory_type)
            else:
                vec_rows = await conn.fetch("""
                    SELECT id,
                           1.0 - (embedding <=> $1::halfvec) AS cosine_sim
                    FROM memories
                    WHERE embedding IS NOT NULL
                      AND searchable = 1
                      AND ($2::text IS NULL OR project = $2)
                    ORDER BY embedding <=> $1::halfvec
                    LIMIT $3
                """, vec, project_param, VECTOR_SEARCH_K)
        except Exception as e:
            logger.warning(f'Vector search failed, falling back to FTS: {e}')
            return await _fts_search_pg(conn, query_text, project, limit, memory_type=memory_type)

        if not vec_rows:
            return await _fts_search_pg(conn, query_text, project, limit, memory_type=memory_type)

        id_to_cosine = {r['id']: float(r['cosine_sim']) for r in vec_rows}
        ids = list(id_to_cosine.keys())

        # Hybrid re-rank: combine vector similarity + FTS rank
        rows = await conn.fetch("""
            SELECT m.id, m.title,
                   SUBSTRING(m.content_md, 1, 500) AS snippet,
                   m.memory_type, m.project, m.module,
                   m.created_at, m.access_count, m.confidence_score,
                   COALESCE(ts_rank(
                       to_tsvector('english', m.title || ' ' || m.content_md),
                       plainto_tsquery('english', $1)
                   ), 0.0) AS fts_score
            FROM memories m
            WHERE m.id = ANY($2)
        """, query_text, ids)

        results = []
        for row in rows:
            cosine_sim = id_to_cosine.get(row['id'], 0.0)
            fts = abs(float(row['fts_score']))
            raw = round(0.7 * cosine_sim + 0.3 * min(fts, 1.0), 4)
            created_str = _iso(row['created_at'])
            mem = {
                'created_at': created_str,
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
                'created_at': created_str,
            })

        results.sort(key=lambda x: x['score'], reverse=True)
        return results[:limit], False, ''


# ── CRUD helpers ───────────────────────────────────────────────────────────────

async def get_memory_pg(pool, memory_id=None, title=None, memory_type=None, project=None) -> Optional[dict]:
    async with pool.acquire() as conn:
        if memory_id:
            if project:
                row = await conn.fetchrow("""
                    SELECT id, title, content_md, memory_type, project, module,
                           tags, resolution, access_count, created_at, updated_at
                    FROM memories WHERE id = $1 AND project = $2
                """, memory_id, project)
            else:
                row = await conn.fetchrow("""
                    SELECT id, title, content_md, memory_type, project, module,
                           tags, resolution, access_count, created_at, updated_at
                    FROM memories WHERE id = $1
                """, memory_id)
        elif memory_type:
            if project:
                row = await conn.fetchrow("""
                    SELECT id, title, content_md, memory_type, project, module,
                           tags, resolution, access_count, created_at, updated_at
                    FROM memories WHERE title = $1 AND memory_type = $2 AND project = $3
                """, title, memory_type, project)
            else:
                row = await conn.fetchrow("""
                    SELECT id, title, content_md, memory_type, project, module,
                           tags, resolution, access_count, created_at, updated_at
                    FROM memories WHERE title = $1 AND memory_type = $2
                """, title, memory_type)
        else:
            if project:
                row = await conn.fetchrow("""
                    SELECT id, title, content_md, memory_type, project, module,
                           tags, resolution, access_count, created_at, updated_at
                    FROM memories WHERE title = $1 AND project = $2 LIMIT 1
                """, title, project)
            else:
                row = await conn.fetchrow("""
                    SELECT id, title, content_md, memory_type, project, module,
                           tags, resolution, access_count, created_at, updated_at
                    FROM memories WHERE title = $1 LIMIT 1
                """, title)
    return _row_to_dict(row) if row else None


async def log_run_pg(pool, data: dict, run_id: str) -> None:
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO prompt_runs
               (id, project, runner, prompt_name, status, output_summary,
                tokens_input, tokens_output, cost_usd)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
        """,
            run_id,
            data.get('project', 'global'),
            data.get('runner'),
            data.get('prompt_name'),
            data.get('status', 'success'),
            data.get('output_summary'),
            data.get('tokens_input'),
            data.get('tokens_output'),
            data.get('cost_usd'),
        )


async def log_error_pg(pool, data: dict, error_id: str) -> None:
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO error_log
               (id, project, runner, error_type, message, stack_trace, context_md)
            VALUES ($1,$2,$3,$4,$5,$6,$7)
        """,
            error_id,
            data.get('project', 'global'),
            data.get('runner'),
            data.get('error_type'),
            data.get('message') or data.get('error', ''),
            data.get('stack_trace'),
            data.get('context_md'),
        )


async def get_schema_pg(pool) -> dict:
    async with pool.acquire() as conn:
        table_rows = await conn.fetch("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
            ORDER BY table_name
        """)
        col_rows = await conn.fetch("""
            SELECT table_name, column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = 'public'
            ORDER BY table_name, ordinal_position
        """)

    tables = [r['table_name'] for r in table_rows]
    schema: dict = {}
    for r in col_rows:
        t = r['table_name']
        schema.setdefault(t, []).append(f"{r['column_name']} {r['data_type']}")

    return {
        'engine': 'postgresql + asyncpg + pgvector',
        'tables': tables,
        'schema': {t: ', '.join(cols) for t, cols in schema.items()},
    }


async def get_prompt_pg(pool, prompt_name: str, project: str = None) -> Optional[dict]:
    async with pool.acquire() as conn:
        if project:
            row = await conn.fetchrow("""
                SELECT id, title, content_md, project, access_count, created_at
                FROM memories WHERE title = $1 AND memory_type = 'prompt' AND project = $2
            """, prompt_name, project)
        else:
            row = await conn.fetchrow("""
                SELECT id, title, content_md, project, access_count, created_at
                FROM memories WHERE title = $1 AND memory_type = 'prompt'
            """, prompt_name)
    return _row_to_dict(row) if row else None


async def bump_access_count_pg(pool, memory_id: str) -> None:
    async with pool.acquire() as conn:
        await conn.execute("""
            UPDATE memories SET access_count = access_count + 1 WHERE id = $1
        """, memory_id)


async def add_token_pg(pool, token_id: str, token: str, person_name: str, role: str) -> None:
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO access_tokens (id, token, person_name, role, active)
            VALUES ($1,$2,$3,$4,1)
        """, token_id, token, person_name, role)


async def list_by_type_pg(pool, memory_type: str, project: str, limit: int,
                          pending_review=None, status: str = None) -> list:
    # Map status string to pending_review value
    if status is not None and pending_review is None:
        if status == 'pending':
            pending_review = 1
        elif status == 'resolved':
            pending_review = 0
    # global → sees ALL memories; specific project → scoped to that project only
    project_param = None if project == 'global' else project
    async with pool.acquire() as conn:
        if pending_review is not None:
            rows = await conn.fetch("""
                SELECT id, title,
                       SUBSTRING(content_md, 1, 300) AS snippet,
                       project, access_count, created_by, created_at
                FROM memories
                WHERE memory_type = $1
                  AND ($2::text IS NULL OR project = $2)
                  AND pending_review = $3
                ORDER BY access_count DESC, created_at DESC
                LIMIT $4
            """, memory_type, project_param, pending_review, limit)
        else:
            rows = await conn.fetch("""
                SELECT id, title,
                       SUBSTRING(content_md, 1, 300) AS snippet,
                       project, access_count, created_by, created_at
                FROM memories
                WHERE memory_type = $1
                  AND ($2::text IS NULL OR project = $2)
                ORDER BY access_count DESC, created_at DESC
                LIMIT $3
            """, memory_type, project_param, limit)
    return [_row_to_dict(r) for r in rows]


async def change_memory_type_pg(pool, memory_id: str, new_type: str) -> Optional[dict]:
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT id, title FROM memories
            WHERE id = $1 AND memory_type = 'requirement'
        """, memory_id)
        if not row:
            return None
        await conn.execute("""
            UPDATE memories
            SET memory_type = $1, pending_review = 0, updated_at = NOW()
            WHERE id = $2
        """, new_type, memory_id)
    return dict(row) if row else None


async def list_projects_pg(pool) -> list[str]:
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT DISTINCT project
            FROM memories
            WHERE project IS NOT NULL AND project != ''
            ORDER BY project
        """)
    return [r['project'] for r in rows]


async def list_all_memories_pg(pool, project: str = 'global', limit: int = 250) -> list[dict]:
    project_param = None if project == 'global' else project
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT id, title,
                   SUBSTRING(content_md, 1, 280) AS snippet,
                   content_md, memory_type, project, module, tags,
                   access_count, created_by, pending_review, resolved, created_at
            FROM memories
            WHERE searchable = 1
              AND ($1::text IS NULL OR project = $1)
            ORDER BY access_count DESC, created_at DESC
            LIMIT $2
        """, project_param, limit)
    out = []
    for row in rows:
        item = _row_to_dict(row)
        try:
            item['tags'] = json.loads(item.get('tags') or '[]')
        except (TypeError, json.JSONDecodeError):
            item['tags'] = []
        out.append(item)
    return out


async def debug_count_pg(pool) -> int:
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT COUNT(*) AS n FROM memories")
    return row['n'] if row else 0


async def verify_token_pg(pool, token: str) -> Optional[str]:
    """Return the role string for an active token, or None if not found."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT role FROM access_tokens WHERE token = $1 AND active = 1",
            token,
        )
    return row['role'] if row else None
