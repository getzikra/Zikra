"""PostgreSQL backend for Zikra using asyncpg + pgvector.

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
    pinned           INTEGER DEFAULT 0,
    created_at   TIMESTAMPTZ DEFAULT NOW(),
    updated_at   TIMESTAMPTZ DEFAULT NOW(),
    last_accessed_at TIMESTAMPTZ,
    embedding    halfvec(3072),
    UNIQUE (title, memory_type, project)
);

CREATE INDEX IF NOT EXISTS idx_memories_project
    ON memories(project, memory_type);

CREATE TABLE IF NOT EXISTS prompt_runs (
    id                     TEXT PRIMARY KEY,
    project                TEXT,
    runner                 TEXT,
    prompt_id              TEXT,
    prompt_name            TEXT,
    status                 TEXT DEFAULT 'success',
    output_summary         TEXT,
    tokens_input           INTEGER,
    tokens_output          INTEGER,
    tokens_cache_read      INTEGER,
    tokens_cache_creation  INTEGER,
    cost_usd               REAL,
    session_id             TEXT,
    created_at             TIMESTAMPTZ DEFAULT NOW()
);
-- NOTE: indexes on prompt_id/prompt_name live in the _migrations block below
-- so they run AFTER ADD COLUMN statements on pre-existing deployments.

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
    id            TEXT PRIMARY KEY,
    token         TEXT NOT NULL UNIQUE,
    person_name   TEXT,
    role          TEXT DEFAULT 'owner',
    active        INTEGER DEFAULT 1,
    token_name    TEXT,
    project_scope TEXT,
    created_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS token_hits (
    id      TEXT PRIMARY KEY,
    label   TEXT NOT NULL,
    command TEXT NOT NULL,
    ts      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_token_hits_label_ts ON token_hits (label, ts DESC);
CREATE INDEX IF NOT EXISTS idx_token_hits_ts ON token_hits (ts DESC);

CREATE TABLE IF NOT EXISTS retrievals (
    id        TEXT PRIMARY KEY,
    memory_id TEXT NOT NULL,
    source    TEXT NOT NULL,
    query     TEXT,
    ts        TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_retrievals_memory_ts ON retrievals (memory_id, ts DESC);
CREATE INDEX IF NOT EXISTS idx_retrievals_ts ON retrievals (ts DESC);
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
    for k in ('created_at', 'updated_at', 'last_accessed_at'):
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
        # Migration guards — safe to run on every startup (IF NOT EXISTS / no-ops on current schema)
        _migrations = [
            "ALTER TABLE prompt_runs ADD COLUMN IF NOT EXISTS prompt_name TEXT NULL",
            "ALTER TABLE prompt_runs ADD COLUMN IF NOT EXISTS prompt_id TEXT NULL",
            "ALTER TABLE prompt_runs ADD COLUMN IF NOT EXISTS tokens_cache_read INTEGER NULL",
            "ALTER TABLE prompt_runs ADD COLUMN IF NOT EXISTS tokens_cache_creation INTEGER NULL",
            "CREATE INDEX IF NOT EXISTS idx_prompt_runs_prompt_id ON prompt_runs(prompt_id)",
            "CREATE INDEX IF NOT EXISTS idx_prompt_runs_prompt_name ON prompt_runs(prompt_name)",
            # v1.0.6: server-side handshake for prompt_id <-> run linkage
            """CREATE TABLE IF NOT EXISTS pending_runs (
                runner     TEXT NOT NULL,
                project    TEXT NOT NULL DEFAULT 'global',
                prompt_id  TEXT NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                PRIMARY KEY (runner, project)
            )""",
            # v1.0.7: wikilink edges for [[title]] references
            """CREATE TABLE IF NOT EXISTS memory_links (
                from_id TEXT NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
                to_id   TEXT NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
                anchor  TEXT NOT NULL,
                PRIMARY KEY (from_id, to_id)
            )""",
            "CREATE INDEX IF NOT EXISTS idx_memory_links_to ON memory_links(to_id)",
            # v1.0.10: per-token usage tracking (append-only)
            """CREATE TABLE IF NOT EXISTS token_hits (
                id      TEXT PRIMARY KEY,
                label   TEXT NOT NULL,
                command TEXT NOT NULL,
                ts      TIMESTAMPTZ DEFAULT NOW()
            )""",
            "CREATE INDEX IF NOT EXISTS idx_token_hits_label_ts ON token_hits (label, ts DESC)",
            "CREATE INDEX IF NOT EXISTS idx_token_hits_ts ON token_hits (ts DESC)",
            # v1.0.10: per-project token scoping (null = unrestricted)
            "ALTER TABLE access_tokens ADD COLUMN IF NOT EXISTS project_scope TEXT NULL",
            # v1.1.0: retrieval logging + pin/access-aware scoring + session-level run dedup
            """CREATE TABLE IF NOT EXISTS retrievals (
                id        TEXT PRIMARY KEY,
                memory_id TEXT NOT NULL,
                source    TEXT NOT NULL,
                query     TEXT,
                ts        TIMESTAMPTZ DEFAULT NOW()
            )""",
            "CREATE INDEX IF NOT EXISTS idx_retrievals_memory_ts ON retrievals (memory_id, ts DESC)",
            "CREATE INDEX IF NOT EXISTS idx_retrievals_ts ON retrievals (ts DESC)",
            "ALTER TABLE memories ADD COLUMN IF NOT EXISTS last_accessed_at TIMESTAMPTZ NULL",
            "ALTER TABLE memories ADD COLUMN IF NOT EXISTS pinned INTEGER DEFAULT 0",
            "ALTER TABLE prompt_runs ADD COLUMN IF NOT EXISTS session_id TEXT NULL",
            """CREATE UNIQUE INDEX IF NOT EXISTS idx_prompt_runs_runner_session
               ON prompt_runs (runner, session_id) WHERE session_id IS NOT NULL""",
            # v1.1.0: server-side transcript distillation queue
            """CREATE TABLE IF NOT EXISTS session_ingests (
                id               TEXT PRIMARY KEY,
                runner           TEXT NOT NULL,
                project          TEXT NOT NULL DEFAULT 'global',
                session_id       TEXT,
                cwd              TEXT,
                transcript_tail  TEXT NOT NULL,
                status           TEXT NOT NULL DEFAULT 'pending',
                error            TEXT,
                memories_created INTEGER DEFAULT 0,
                created_at       TIMESTAMPTZ DEFAULT NOW(),
                distilled_at     TIMESTAMPTZ
            )""",
            "CREATE INDEX IF NOT EXISTS idx_session_ingests_status ON session_ingests (status, created_at)",
            "CREATE INDEX IF NOT EXISTS idx_session_ingests_session ON session_ingests (runner, session_id)",
        ]
        for stmt in _migrations:
            try:
                await conn.execute(stmt)
            except Exception as e:
                logger.warning(f'Migration skipped ({stmt[:60]}...): {e}')
        try:
            await conn.execute(_PG_VEC_INDEX)
        except Exception as e:
            logger.warning(f'Vector index creation skipped, falling back to FTS: {e}')

    return _pg_pool


def get_pg_pool() -> Optional['asyncpg.Pool']:
    return _pg_pool


# ── save_memory ───────────────────────────────────────────────────────────────

async def _store_wikilinks_pg(conn, from_id: str, content_md: str, project: str) -> None:
    """Replace from_id's rows in memory_links with edges parsed from content_md."""
    from zikra.db import _extract_wikilinks
    await conn.execute("DELETE FROM memory_links WHERE from_id = $1", from_id)
    anchors = _extract_wikilinks(content_md)
    if not anchors:
        return
    for anchor in anchors:
        row = await conn.fetchrow(
            """SELECT id FROM memories
               WHERE title = $1 AND (project = $2 OR project = 'global')
               ORDER BY (project = $2) DESC LIMIT 1""",
            anchor, project,
        )
        if not row:
            continue
        await conn.execute(
            """INSERT INTO memory_links(from_id, to_id, anchor)
               VALUES ($1, $2, $3)
               ON CONFLICT DO NOTHING""",
            from_id, row['id'], anchor,
        )


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

        resolved_id = row['id'] if row else memory_id
        await _store_wikilinks_pg(
            conn, resolved_id,
            data.get('content_md') or data.get('content', ''),
            data.get('project', 'global'),
        )

        # Pin state changes only when the caller explicitly sends 'pinned' —
        # a re-save without the field never silently unpins.
        if 'pinned' in data:
            await conn.execute(
                "UPDATE memories SET pinned = $1 WHERE id = $2",
                1 if data['pinned'] else 0, resolved_id
            )

    return resolved_id


async def nearest_projects_pg(pool: 'asyncpg.Pool', embedding: list, k: int) -> list[dict]:
    vec = _vec_str(embedding)
    if vec is None:
        return []
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT project, 1.0 - (embedding <=> $1::halfvec) AS sim
            FROM memories
            WHERE embedding IS NOT NULL AND searchable = 1
            ORDER BY embedding <=> $1::halfvec
            LIMIT $2
        """, vec, k)
    return [{'project': row['project'], 'sim': float(row['sim'])} for row in rows]


async def find_recent_similar_pg(pool: 'asyncpg.Pool', created_by, project,
                                 memory_types: list, window_min: int,
                                 embedding: list) -> Optional[dict]:
    if not created_by:
        return None
    vec = _vec_str(embedding)
    if vec is None:
        return None
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT id, title, 1.0 - (embedding <=> $1::halfvec) AS sim
            FROM memories
            WHERE embedding IS NOT NULL
              AND searchable=1
              AND created_by=$2
              AND project=$3
              AND memory_type = ANY($4)
              AND created_at >= NOW() - ($5 * interval '1 minute')
            ORDER BY embedding <=> $1::halfvec
            LIMIT 1
        """, vec, created_by, project, memory_types, window_min)
    return {'id': row['id'], 'title': row['title'], 'sim': float(row['sim'])} if row else None


async def update_memory_content_pg(pool: 'asyncpg.Pool', memory_id: str,
                                   content_md: str, embedding: list) -> None:
    vec = _vec_str(embedding)
    async with pool.acquire() as conn:
        await conn.execute("""
            UPDATE memories SET content_md=$1, embedding=$2::halfvec, updated_at=NOW() WHERE id=$3
        """, content_md, vec, memory_id)


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
                       pinned, last_accessed_at,
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
                       pinned, last_accessed_at,
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
                           pinned, last_accessed_at,
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
                           pinned, last_accessed_at,
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
            'created_at': created_str,
            'last_accessed_at': _iso(row['last_accessed_at']),
            'access_count': row['access_count'],
            'confidence_score': row['confidence_score'],
            'pinned': row['pinned'],
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
                   m.pinned, m.last_accessed_at,
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
                'created_at': created_str,
                'last_accessed_at': _iso(row['last_accessed_at']),
                'access_count': row['access_count'],
                'confidence_score': row['confidence_score'],
                'pinned': row['pinned'],
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
                           tags, resolution, access_count, created_at, updated_at,
                           pinned, last_accessed_at, confidence_score
                    FROM memories WHERE id = $1 AND project = $2
                """, memory_id, project)
            else:
                row = await conn.fetchrow("""
                    SELECT id, title, content_md, memory_type, project, module,
                           tags, resolution, access_count, created_at, updated_at,
                           pinned, last_accessed_at, confidence_score
                    FROM memories WHERE id = $1
                """, memory_id)
        elif memory_type:
            if project:
                row = await conn.fetchrow("""
                    SELECT id, title, content_md, memory_type, project, module,
                           tags, resolution, access_count, created_at, updated_at,
                           pinned, last_accessed_at, confidence_score
                    FROM memories WHERE title = $1 AND memory_type = $2 AND project = $3
                """, title, memory_type, project)
            else:
                row = await conn.fetchrow("""
                    SELECT id, title, content_md, memory_type, project, module,
                           tags, resolution, access_count, created_at, updated_at,
                           pinned, last_accessed_at, confidence_score
                    FROM memories WHERE title = $1 AND memory_type = $2
                """, title, memory_type)
        else:
            if project:
                row = await conn.fetchrow("""
                    SELECT id, title, content_md, memory_type, project, module,
                           tags, resolution, access_count, created_at, updated_at,
                           pinned, last_accessed_at, confidence_score
                    FROM memories WHERE title = $1 AND project = $2 LIMIT 1
                """, title, project)
            else:
                row = await conn.fetchrow("""
                    SELECT id, title, content_md, memory_type, project, module,
                           tags, resolution, access_count, created_at, updated_at,
                           pinned, last_accessed_at, confidence_score
                    FROM memories WHERE title = $1 LIMIT 1
                """, title)
    return _row_to_dict(row) if row else None


async def log_run_pg(pool, data: dict, run_id: str) -> str:
    """Insert a run row; upserts on (runner, session_id) when session_id is
    present so hook + watcher converge on one row per session. Returns row id."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO prompt_runs
               (id, project, runner, prompt_id, prompt_name, status, output_summary,
                tokens_input, tokens_output, tokens_cache_read, tokens_cache_creation,
                cost_usd, session_id)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
            ON CONFLICT (runner, session_id) WHERE session_id IS NOT NULL DO UPDATE SET
                project               = EXCLUDED.project,
                prompt_id             = COALESCE(EXCLUDED.prompt_id, prompt_runs.prompt_id),
                prompt_name           = COALESCE(EXCLUDED.prompt_name, prompt_runs.prompt_name),
                status                = EXCLUDED.status,
                output_summary        = CASE
                    WHEN LENGTH(COALESCE(EXCLUDED.output_summary, '')) > LENGTH(COALESCE(prompt_runs.output_summary, ''))
                    THEN EXCLUDED.output_summary ELSE prompt_runs.output_summary END,
                tokens_input          = GREATEST(COALESCE(EXCLUDED.tokens_input, 0), COALESCE(prompt_runs.tokens_input, 0)),
                tokens_output         = GREATEST(COALESCE(EXCLUDED.tokens_output, 0), COALESCE(prompt_runs.tokens_output, 0)),
                tokens_cache_read     = GREATEST(COALESCE(EXCLUDED.tokens_cache_read, 0), COALESCE(prompt_runs.tokens_cache_read, 0)),
                tokens_cache_creation = GREATEST(COALESCE(EXCLUDED.tokens_cache_creation, 0), COALESCE(prompt_runs.tokens_cache_creation, 0)),
                cost_usd              = COALESCE(EXCLUDED.cost_usd, prompt_runs.cost_usd)
            RETURNING id
        """,
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
        )
    return row['id'] if row else run_id


async def create_ingest_pg(pool, data: dict, ingest_id: str) -> None:
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO session_ingests
               (id, runner, project, session_id, cwd, transcript_tail, status)
            VALUES ($1,$2,$3,$4,$5,$6,'pending')
        """,
            ingest_id,
            data.get('runner'),
            data.get('project', 'global'),
            data.get('session_id'),
            data.get('cwd'),
            data.get('transcript_tail', ''),
        )


async def fetch_ingest_pg(pool, ingest_id: str) -> Optional[dict]:
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM session_ingests WHERE id = $1", ingest_id)
    if not row:
        return None
    d = dict(row)
    for k in ('created_at', 'distilled_at'):
        if k in d:
            d[k] = _iso(d[k])
    return d


async def finish_ingest_pg(pool, ingest_id: str, status: str, error: str = None,
                           memories_created: int = 0) -> None:
    async with pool.acquire() as conn:
        await conn.execute("""
            UPDATE session_ingests
            SET status = $1, error = $2, memories_created = $3,
                distilled_at = NOW(),
                transcript_tail = CASE WHEN $1 = 'distilled' THEN '' ELSE transcript_tail END
            WHERE id = $4
        """, status, error, memories_created, ingest_id)


async def list_pending_ingests_pg(pool, limit: int = 20) -> list:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id FROM session_ingests WHERE status = 'pending' ORDER BY created_at LIMIT $1",
            limit,
        )
    return [r['id'] for r in rows]


async def record_pending_run_pg(pool, runner: str, prompt_id: str, project: str) -> None:
    """v1.0.6 handshake: remember that `runner` just fetched `prompt_id`."""
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO pending_runs (runner, project, prompt_id) VALUES ($1,$2,$3)
            ON CONFLICT (runner, project) DO UPDATE SET
                prompt_id = EXCLUDED.prompt_id,
                created_at = NOW()
        """, runner, project, prompt_id)


async def consume_pending_run_pg(pool, runner: str, project: str) -> Optional[str]:
    """Atomically read-and-delete the pending prompt_id for (runner, project)."""
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "SELECT prompt_id FROM pending_runs WHERE runner=$1 AND project=$2 FOR UPDATE",
                runner, project
            )
            if not row:
                return None
            await conn.execute(
                "DELETE FROM pending_runs WHERE runner=$1 AND project=$2",
                runner, project
            )
            return row['prompt_id']


async def list_runs_pg(pool, project: str = 'global', prompt_id: str = None,
                        prompt_name: str = None, limit: int = 100) -> list[dict]:
    """List prompt_runs rows joined with the prompt title from memories."""
    where = []
    args: list = []
    if project and project != 'global':
        args.append(project); where.append(f'r.project = ${len(args)}')
    if prompt_id:
        args.append(prompt_id); where.append(f'r.prompt_id = ${len(args)}')
    if prompt_name:
        args.append(prompt_name); where.append(f'r.prompt_name = ${len(args)}')
    args.append(limit)
    where_sql = ('WHERE ' + ' AND '.join(where)) if where else ''
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
        LIMIT ${len(args)}
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *args)
    return [_row_to_dict(r) for r in rows]


async def run_stats_pg(pool, project: str = 'global', prompt_id: str = None,
                        prompt_name: str = None) -> dict:
    """Aggregate token usage across prompt_runs (filterable)."""
    where = []
    args: list = []
    if project and project != 'global':
        args.append(project); where.append(f'project = ${len(args)}')
    if prompt_id:
        args.append(prompt_id); where.append(f'prompt_id = ${len(args)}')
    if prompt_name:
        args.append(prompt_name); where.append(f'prompt_name = ${len(args)}')
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
    async with pool.acquire() as conn:
        row = await conn.fetchrow(sql, *args)
    return dict(row) if row else {}


async def update_memory_flags_pg(pool, memory_id: str, pinned: int = None,
                                 searchable: int = None,
                                 pending_review: int = None) -> bool:
    sets, params = [], []
    if pinned is not None:
        params.append(int(pinned)); sets.append(f'pinned = ${len(params)}')
    if searchable is not None:
        params.append(int(searchable)); sets.append(f'searchable = ${len(params)}')
    if pending_review is not None:
        params.append(int(pending_review)); sets.append(f'pending_review = ${len(params)}')
    if not sets:
        return False
    params.append(memory_id)
    async with pool.acquire() as conn:
        result = await conn.execute(
            f"UPDATE memories SET {', '.join(sets)}, updated_at = NOW() WHERE id = ${len(params)}",
            *params)
    return result.endswith('1')


async def activity_stats_pg(pool, project: str = 'global', days: int = 30) -> dict:
    project_param = None if project == 'global' else project
    async with pool.acquire() as conn:
        runs = await conn.fetch(
            """SELECT DATE(created_at)::text AS d, COUNT(*)::int AS n,
                      COALESCE(SUM(tokens_input),0)::bigint AS tokens_in,
                      COALESCE(SUM(tokens_output),0)::bigint AS tokens_out,
                      COALESCE(SUM(tokens_cache_read),0)::bigint AS tokens_cache
               FROM prompt_runs
               WHERE created_at >= NOW() - ($2 * interval '1 day')
                 AND ($1::text IS NULL OR project = $1)
               GROUP BY DATE(created_at) ORDER BY d""",
            project_param, int(days))
        memories = await conn.fetch(
            """SELECT DATE(created_at)::text AS d, memory_type, COUNT(*)::int AS n
               FROM memories
               WHERE created_at >= NOW() - ($2 * interval '1 day')
                 AND ($1::text IS NULL OR project = $1)
               GROUP BY DATE(created_at), memory_type ORDER BY d""",
            project_param, int(days))
        errors = await conn.fetch(
            """SELECT DATE(created_at)::text AS d, COUNT(*)::int AS n
               FROM error_log
               WHERE created_at >= NOW() - ($2 * interval '1 day')
                 AND ($1::text IS NULL OR project = $1)
               GROUP BY DATE(created_at) ORDER BY d""",
            project_param, int(days))
    return {
        'runs': [dict(r) for r in runs],
        'memories': [dict(r) for r in memories],
        'errors': [dict(r) for r in errors],
        'days': days,
    }


async def recent_memories_pg(pool, project: str = 'global', limit: int = 20) -> list:
    project_param = None if project == 'global' else project
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT id, title, SUBSTRING(content_md, 1, 280) AS snippet, memory_type,
                      project, created_by, pending_review, pinned, created_at
               FROM memories WHERE searchable = 1
                 AND ($1::text IS NULL OR project = $1)
               ORDER BY created_at DESC LIMIT $2""",
            project_param, limit)
    return [{**dict(r), 'created_at': _iso(r['created_at'])} for r in rows]


async def recent_errors_pg(pool, project: str = 'global', limit: int = 20) -> list:
    project_param = None if project == 'global' else project
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT id, project, runner, error_type, message,
                      SUBSTRING(context_md, 1, 500) AS context_md, created_at
               FROM error_log
               WHERE ($1::text IS NULL OR project = $1)
               ORDER BY created_at DESC LIMIT $2""",
            project_param, limit)
    return [{**dict(r), 'created_at': _iso(r['created_at'])} for r in rows]


async def list_consolidation_candidates_pg(pool, project: str, min_age_days: int,
                                           limit: int = 200) -> list:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT id, title, content_md, created_at FROM memories
               WHERE project = $1
                 AND memory_type IN ('conversation', 'diary')
                 AND searchable = 1
                 AND COALESCE(pinned, 0) = 0
                 AND created_at < NOW() - ($2 * interval '1 day')
               ORDER BY created_at
               LIMIT $3""",
            project, int(min_age_days), limit,
        )
    return [{**dict(r), 'created_at': _iso(r['created_at'])} for r in rows]


async def archive_memories_pg(pool, memory_ids: list, note: str) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """UPDATE memories SET searchable = 0, resolution = $1, updated_at = NOW()
               WHERE id = ANY($2::text[])""",
            note, list(memory_ids),
        )


async def count_recent_errors_pg(pool, project: str, error_type: str,
                                 message: str, days: int = 7) -> int:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT COUNT(*) AS n FROM error_log
               WHERE project = $1 AND COALESCE(error_type,'') = COALESCE($2,'')
                 AND message = $3
                 AND created_at >= NOW() - ($4 * interval '1 day')""",
            project, error_type, message, int(days),
        )
    return row['n'] if row else 0


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


async def hygiene_report_pg(pool, project: str, stale_days: int) -> list:
    """PG implementation of the orphan/stale scan. See db.hygiene_report()."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                m.id,
                m.title,
                m.memory_type,
                m.project,
                m.access_count,
                EXTRACT(
                    day FROM now() - COALESCE(m.last_accessed_at, m.updated_at, m.created_at)
                )::int AS days_idle,
                COUNT(l.from_id)::int AS backlink_count
            FROM memories m
            LEFT JOIN memory_links l ON l.to_id = m.id
            WHERE m.project = $1
              AND COALESCE(m.pinned, 0) = 0
            GROUP BY m.id, m.title, m.memory_type, m.project,
                     m.access_count, m.last_accessed_at, m.updated_at, m.created_at
            HAVING EXTRACT(
                       day FROM now() - COALESCE(m.last_accessed_at, m.updated_at, m.created_at)
                   ) > $2
               AND COUNT(l.from_id) = 0
            ORDER BY days_idle DESC
            """,
            project, stale_days,
        )
    return [dict(r) for r in rows]


async def fetch_links_between_pg(pool, memory_ids: list) -> list:
    """Return memory_links rows where both endpoints are in memory_ids."""
    if not memory_ids:
        return []
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT from_id, to_id, anchor FROM memory_links
               WHERE from_id = ANY($1::text[]) AND to_id = ANY($1::text[])""",
            list(memory_ids),
        )
    return [dict(r) for r in rows]


async def fetch_memory_links_pg(pool, memory_id: str) -> dict:
    """Return {links_out, links_in} for a memory via memory_links."""
    async with pool.acquire() as conn:
        out_rows = await conn.fetch(
            """SELECT m.id, m.title, m.memory_type
               FROM memory_links l JOIN memories m ON m.id = l.to_id
               WHERE l.from_id = $1 ORDER BY m.title""",
            memory_id,
        )
        in_rows = await conn.fetch(
            """SELECT m.id, m.title, m.memory_type
               FROM memory_links l JOIN memories m ON m.id = l.from_id
               WHERE l.to_id = $1 ORDER BY m.title""",
            memory_id,
        )
    return {
        'links_out': [dict(r) for r in out_rows],
        'links_in':  [dict(r) for r in in_rows],
    }


async def delete_memory_pg(pool, memory_id: str) -> Optional[dict]:
    """Delete a memory by UUID. Returns {id, title} on success, None if not found."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "DELETE FROM memories WHERE id = $1 RETURNING id, title, memory_type, project",
            memory_id,
        )
    return dict(row) if row else None


async def log_retrievals_pg(pool, memory_ids: list, source: str, query: str = None) -> None:
    from zikra.db import new_id
    async with pool.acquire() as conn:
        await conn.execute("""
            UPDATE memories
            SET access_count = access_count + 1, last_accessed_at = NOW()
            WHERE id = ANY($1::text[])
        """, memory_ids)
        await conn.executemany(
            "INSERT INTO retrievals (id, memory_id, source, query) VALUES ($1,$2,$3,$4)",
            [(new_id(), mid, source, query) for mid in memory_ids]
        )


async def bump_access_count_pg(pool, memory_id: str) -> None:
    await log_retrievals_pg(pool, [memory_id], 'get')


async def add_token_pg(pool, token_id: str, token: str, person_name: str, role: str,
                       project_scope: str = None) -> None:
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO access_tokens (id, token, person_name, role, active, project_scope)
            VALUES ($1,$2,$3,$4,1,$5)
        """, token_id, token, person_name, role, project_scope)


async def token_usage_stats_pg(pool) -> list:
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT
                label,
                COUNT(*)                                                        AS hits_total,
                COUNT(*) FILTER (WHERE ts > NOW() - INTERVAL '7 days')         AS hits_7d,
                COUNT(*) FILTER (WHERE ts > NOW() - INTERVAL '24 hours')       AS hits_24h,
                MAX(ts)                                                         AS last_seen
            FROM token_hits
            GROUP BY label
            ORDER BY hits_total DESC
        """)
    return [dict(r) for r in rows]


async def list_token_labels_pg(pool) -> list:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT person_name FROM access_tokens WHERE active = 1 AND role != 'owner' ORDER BY created_at"
        )
        return [r['person_name'] for r in rows if r['person_name']]


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


async def list_memory_types_pg(pool) -> list[str]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT DISTINCT memory_type FROM memories WHERE memory_type IS NOT NULL ORDER BY memory_type")
    return [r['memory_type'] for r in rows]


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
                   access_count, created_by, pending_review, resolved, created_at,
                   pinned, last_accessed_at, confidence_score
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


async def count_memories_pg(pool, project: str) -> int:
    """Return total memory count scoped by project. 'global' sees all."""
    async with pool.acquire() as conn:
        if project == 'global':
            row = await conn.fetchrow(
                "SELECT COUNT(*) AS n FROM memories WHERE searchable = 1")
        else:
            row = await conn.fetchrow(
                "SELECT COUNT(*) AS n FROM memories WHERE searchable = 1 AND project = $1",
                project,
            )
    return row['n'] if row else 0


async def debug_count_pg(pool) -> int:
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT COUNT(*) AS n FROM memories")
    return row['n'] if row else 0


async def verify_token_pg(pool, token: str) -> Optional[dict]:
    """Return {'role', 'label', 'project_scope'} for an active token, or None."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT role, person_name, project_scope FROM access_tokens WHERE token = $1 AND active = 1",
            token,
        )
    if not row:
        return None
    return {
        'role': row['role'],
        'label': row['person_name'] or '',
        'project_scope': row['project_scope'],
    }


async def log_token_hit_pg(pool, label: str, command: str) -> None:
    import uuid as _uuid
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO token_hits (id, label, command) VALUES ($1, $2, $3)",
            str(_uuid.uuid4()), label, command,
        )
