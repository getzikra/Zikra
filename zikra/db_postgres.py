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

_PG_ARCHITECTURE_DDL = (
    "ALTER TABLE memories ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'current'",
    "ALTER TABLE memories ADD COLUMN IF NOT EXISTS supersedes_id TEXT NULL",
    "ALTER TABLE memories ADD COLUMN IF NOT EXISTS environment TEXT NULL",
    "ALTER TABLE memories ADD COLUMN IF NOT EXISTS evidence TEXT NULL",
    "ALTER TABLE memories ADD COLUMN IF NOT EXISTS decision_kind TEXT NULL",
    "CREATE INDEX IF NOT EXISTS idx_memories_arch_kind ON memories (project, module, status, memory_type, decision_kind)",
    """CREATE TABLE IF NOT EXISTS repo_sync_state (
        project TEXT NOT NULL, repo_path TEXT NOT NULL,
        last_synced_commit TEXT, synced_at TIMESTAMPTZ DEFAULT NOW(),
        PRIMARY KEY (project, repo_path)
    )""",
    """CREATE TABLE IF NOT EXISTS architecture_snapshots (
        id TEXT PRIMARY KEY,
        project TEXT NOT NULL,
        environment TEXT NOT NULL DEFAULT 'all'
            CHECK (environment IN ('all', 'dev', 'prod')),
        status TEXT NOT NULL DEFAULT 'draft'
            CHECK (status IN ('draft', 'published', 'archived')),
        model TEXT, prompt_version TEXT, summary TEXT,
        document_json JSONB NOT NULL,
        source_digest TEXT,
        source_count INTEGER NOT NULL DEFAULT 0 CHECK (source_count >= 0),
        evidence_coverage REAL NOT NULL DEFAULT 0
            CHECK (evidence_coverage >= 0 AND evidence_coverage <= 1),
        generated_at TIMESTAMPTZ DEFAULT NOW(),
        published_at TIMESTAMPTZ,
        created_by TEXT
    )""",
    "CREATE INDEX IF NOT EXISTS idx_architecture_snapshots_project ON architecture_snapshots (project, environment, status, generated_at DESC)",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_architecture_one_published ON architecture_snapshots (project, environment) WHERE status = 'published'",
    """CREATE TABLE IF NOT EXISTS architecture_project_state (
        project TEXT PRIMARY KEY,
        last_run_at TIMESTAMPTZ,
        last_status TEXT,
        last_error TEXT,
        last_snapshot_id TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS architecture_generation_state (
        project TEXT NOT NULL,
        environment TEXT NOT NULL CHECK (environment IN ('all', 'dev', 'prod')),
        local_run_date DATE NOT NULL,
        source_digest TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN
            ('running', 'success', 'failed', 'cancelled', 'skipped')),
        attempt_id TEXT NOT NULL,
        started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        finished_at TIMESTAMPTZ,
        lease_expires_at TIMESTAMPTZ,
        snapshot_id TEXT,
        last_error TEXT,
        PRIMARY KEY (project, environment)
    )""",
)


async def verify_architecture_schema_pg(conn) -> None:
    """Fail closed if the additive architecture migration is incomplete."""
    required_columns = {
        'memories': {'status', 'supersedes_id', 'environment', 'evidence', 'decision_kind'},
        'architecture_snapshots': {
            'id', 'project', 'environment', 'status', 'document_json',
            'source_digest', 'source_count', 'evidence_coverage',
        },
        'architecture_project_state': {
            'project', 'last_run_at', 'last_status', 'last_error', 'last_snapshot_id',
        },
        'architecture_generation_state': {
            'project', 'environment', 'local_run_date', 'source_digest', 'status',
            'attempt_id', 'lease_expires_at', 'snapshot_id',
        },
    }
    rows = await conn.fetch("""
        SELECT table_name, column_name
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = ANY($1::text[])
    """, list(required_columns))
    found = {}
    for row in rows:
        found.setdefault(row['table_name'], set()).add(row['column_name'])
    missing = {
        table: sorted(columns - found.get(table, set()))
        for table, columns in required_columns.items()
        if columns - found.get(table, set())
    }
    index_rows = await conn.fetch("""
        SELECT indexname FROM pg_indexes
        WHERE schemaname = current_schema()
          AND indexname = ANY($1::text[])
    """, ['idx_memories_arch_kind', 'idx_architecture_snapshots_project',
          'idx_architecture_one_published'])
    indexes = {row['indexname'] for row in index_rows}
    missing_indexes = sorted({
        'idx_memories_arch_kind', 'idx_architecture_snapshots_project',
        'idx_architecture_one_published',
    } - indexes)
    if missing or missing_indexes:
        details = []
        if missing:
            details.append('columns=' + json.dumps(missing, sort_keys=True))
        if missing_indexes:
            details.append('indexes=' + ','.join(missing_indexes))
        raise RuntimeError('architecture schema verification failed: ' + '; '.join(details))


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
            # v1.2.0: architecture decisions — supersedes chains on memories + repo sync state
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

        # Architecture generation can transmit project memories to an external
        # model, so this migration is fail-closed rather than best-effort.
        try:
            async with conn.transaction():
                for stmt in _PG_ARCHITECTURE_DDL:
                    await conn.execute(stmt)
                await verify_architecture_schema_pg(conn)
        except Exception as exc:
            logger.error('architecture schema migration failed; startup aborted')
            raise RuntimeError('architecture schema migration failed') from exc

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


async def change_memory_type_pg(pool, memory_id: str, new_type: str,
                                from_type: str = None) -> Optional[dict]:
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT id, title FROM memories
            WHERE id = $1 AND ($2::text IS NULL OR memory_type = $2)
        """, memory_id, from_type)
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


# ── Architecture decisions (v1.2.0) ───────────────────────────────────────────
# Decisions live in memories (memory_type='decision') with status/supersedes_id/
# environment/evidence columns. Reuses the existing table so search, wikilinks,
# and the web UI see decisions without any parallel plumbing.

_DECISION_COLS = """id, title, content_md, project, module, memory_type, decision_kind,
                    status, supersedes_id, environment, evidence,
                    tags, created_by, created_at, updated_at"""


async def save_decision_pg(pool, data: dict, embedding: list) -> str:
    """Upsert a decision row; atomically mark supersedes_id as superseded.

    Identity is (title, memory_type='decision', project) — same as save_memory —
    so re-saving the same titled decision updates it in place instead of
    violating the UNIQUE constraint. A supersedes_id equal to the resolved row
    (self-reference after an upsert) is ignored.
    """
    from zikra.db import new_id
    memory_id = new_id()
    vec = _vec_str(embedding)
    project = data['project']
    module = data['module']
    title = data['title']
    content = data.get('content_md') or data.get('content', '')
    supersedes_id = data.get('supersedes_id')

    async with pool.acquire() as conn:
        async with conn.transaction():
            existing = await conn.fetchrow("""
                SELECT id, module, status, decision_kind
                FROM memories
                WHERE title = $1 AND memory_type = 'decision' AND project = $2
                FOR UPDATE
            """, title, project)
            if existing:
                if existing['decision_kind'] != 'architecture':
                    raise ValueError('a non-architecture decision already uses this title')
                if existing['module'] != module:
                    raise ValueError('an architecture decision title cannot move between modules')
                if existing['status'] != 'current':
                    raise ValueError('a superseded decision is immutable; save a new titled revision')
                if supersedes_id:
                    raise ValueError('supersedes_id is only valid when creating a new titled revision')

            if supersedes_id:
                target = await conn.fetchrow("""
                    SELECT id FROM memories
                    WHERE id = $1 AND project = $2 AND module = $3
                      AND memory_type = 'decision'
                      AND decision_kind = 'architecture'
                      AND status = 'current'
                    FOR UPDATE
                """, supersedes_id, project, module)
                if not target:
                    raise ValueError('supersedes_id must reference a current architecture decision in the same project and module')
                child = await conn.fetchval("""
                    SELECT id FROM memories
                    WHERE supersedes_id = $1 AND decision_kind = 'architecture'
                    LIMIT 1
                """, supersedes_id)
                if child:
                    raise ValueError('supersedes_id already has a successor')

            base_cols = """(id, project, module, memory_type, title, content_md,
                            tags, created_by, searchable,
                            status, supersedes_id, environment, evidence, decision_kind"""
            base_vals = """($1,$2,$3,'decision',$4,$5,$6,$7,1,
                            'current',$8,$9,$10,'architecture'"""
            conflict = """
                ON CONFLICT (title, memory_type, project) DO UPDATE SET
                    content_md    = EXCLUDED.content_md,
                    tags          = EXCLUDED.tags,
                    environment   = EXCLUDED.environment,
                    evidence      = EXCLUDED.evidence,
                    decision_kind = 'architecture',
                    updated_at    = NOW()
            """
            params = [
                memory_id, project, module, title, content,
                json.dumps(data.get('tags') or []), data.get('created_by'),
                supersedes_id, data.get('environment'), data.get('evidence'),
            ]
            if vec is not None:
                row = await conn.fetchrow(
                    f"INSERT INTO memories {base_cols}, embedding) "
                    f"VALUES {base_vals}, $11::halfvec) {conflict} "
                    "RETURNING id",
                    *params, vec,
                )
            else:
                row = await conn.fetchrow(
                    f"INSERT INTO memories {base_cols}) "
                    f"VALUES {base_vals}) {conflict} "
                    "RETURNING id",
                    *params,
                )
            resolved_id = row['id'] if row else memory_id

            if supersedes_id:
                result = await conn.execute("""
                    UPDATE memories SET status = 'superseded', updated_at = NOW()
                    WHERE id = $1 AND project = $2 AND module = $3
                      AND memory_type = 'decision'
                      AND decision_kind = 'architecture'
                      AND status = 'current'
                """, supersedes_id, project, module)
                if result != 'UPDATE 1':
                    raise ValueError('supersedes_id could not be superseded safely')

            await _store_wikilinks_pg(conn, resolved_id, content, project)
    return resolved_id


async def list_decisions_pg(pool, project: str, module: str = None,
                            environment: str = None,
                            current_only: bool = True) -> list:
    """Decisions for one project (strict scope — never cross-project),
    newest first. environment filter matches that env plus env-agnostic
    (NULL) rows, since those apply everywhere."""
    sql = f"""SELECT {_DECISION_COLS} FROM memories
              WHERE memory_type = 'decision'
                AND decision_kind = 'architecture'
                AND project = $1"""
    params: list = [project]
    if current_only:
        sql += " AND status = 'current'"
    if module:
        params.append(module)
        sql += f" AND module = ${len(params)}"
    if environment:
        params.append(environment)
        sql += f" AND (environment = ${len(params)} OR environment IS NULL)"
    sql += " ORDER BY created_at DESC"
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *params)
    return [_row_to_dict(r) for r in rows]


async def get_sync_state_pg(pool, project: str, repo_path: str) -> Optional[dict]:
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT project, repo_path, last_synced_commit, synced_at
            FROM repo_sync_state WHERE project = $1 AND repo_path = $2
        """, project, repo_path)
    if not row:
        return None
    d = dict(row)
    d['synced_at'] = _iso(d.get('synced_at'))
    return d


async def set_sync_state_pg(pool, project: str, repo_path: str,
                            last_synced_commit: str) -> dict:
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO repo_sync_state (project, repo_path, last_synced_commit, synced_at)
            VALUES ($1, $2, $3, NOW())
            ON CONFLICT (project, repo_path) DO UPDATE SET
                last_synced_commit = EXCLUDED.last_synced_commit,
                synced_at          = NOW()
            RETURNING project, repo_path, last_synced_commit, synced_at
        """, project, repo_path, last_synced_commit)
    d = dict(row)
    d['synced_at'] = _iso(d.get('synced_at'))
    return d


# -- Generated architecture snapshots ----------------------------------------

async def list_architecture_sources_pg(pool, project: str, limit: int = 300) -> list[dict]:
    types = [
        'architecture', 'module', 'stack', 'design_doc', 'index', 'reference',
        'audit', 'investigation', 'implementation', 'requirement', 'bug',
        'mockup', 'feedback', 'decision', 'change_log', 'summary', 'note',
        'diary', 'conversation',
    ]
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT id, title, content_md, memory_type, project, module, tags,
                   confidence_score, pinned, status, decision_kind, environment,
                   evidence, created_at, updated_at
            FROM memories
            WHERE project = $1 AND searchable = 1
              AND memory_type = ANY($2::text[])
              AND (memory_type <> 'decision' OR status = 'current')
            ORDER BY
              CASE memory_type
                WHEN 'architecture' THEN 0 WHEN 'module' THEN 1
                WHEN 'stack' THEN 2 WHEN 'design_doc' THEN 3
                WHEN 'index' THEN 4 WHEN 'reference' THEN 5
                WHEN 'audit' THEN 6 WHEN 'investigation' THEN 7
                WHEN 'implementation' THEN 8 WHEN 'requirement' THEN 9
                WHEN 'bug' THEN 10 WHEN 'mockup' THEN 11
                WHEN 'feedback' THEN 12 WHEN 'decision' THEN 13
                WHEN 'change_log' THEN 14 WHEN 'summary' THEN 15
                WHEN 'note' THEN 16 WHEN 'diary' THEN 17 ELSE 18
              END,
              pinned DESC, COALESCE(updated_at, created_at) DESC, id ASC
            LIMIT $3
        """, project, types, limit)
    return [_row_to_dict(row) for row in rows]


def _snapshot_pg_dict(row) -> Optional[dict]:
    if not row:
        return None
    item = dict(row)
    document = item.pop('document_json', {}) or {}
    if isinstance(document, str):
        try:
            document = json.loads(document)
        except json.JSONDecodeError:
            document = {}
    item['document'] = document
    for key in ('generated_at', 'published_at'):
        item[key] = _iso(item.get(key))
    return item


async def save_architecture_snapshot_pg(pool, data: dict) -> dict:
    import uuid as _uuid
    snapshot_id = data.get('id') or str(_uuid.uuid4())
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO architecture_snapshots
                (id, project, environment, status, model, prompt_version,
                 summary, document_json, source_digest, source_count,
                 evidence_coverage, created_by)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8::jsonb,$9,$10,$11,$12)
            RETURNING *
        """, snapshot_id, data['project'], data.get('environment', 'all'),
            data.get('status', 'draft'), data.get('model'), data.get('prompt_version'),
            data.get('summary'), json.dumps(data.get('document') or {}),
            data.get('source_digest'), int(data.get('source_count') or 0),
            float(data.get('evidence_coverage') or 0), data.get('created_by'))
    return _snapshot_pg_dict(row)


async def get_architecture_snapshot_pg(pool, project: str,
                                       environment: str = None,
                                       snapshot_id: str = None,
                                       status: str = None) -> Optional[dict]:
    sql = "SELECT * FROM architecture_snapshots WHERE project = $1"
    params: list = [project]
    order_sql = ''
    if snapshot_id:
        params.append(snapshot_id)
        sql += f" AND id = ${len(params)}"
    elif environment == 'all':
        sql += " AND environment = 'all'"
    elif environment:
        params.append(environment)
        sql += f" AND environment IN (${len(params)}, 'all')"
        order_sql = f'CASE WHEN environment = ${len(params)} THEN 0 ELSE 1 END, '
    if status:
        params.append(status)
        sql += f" AND status = ${len(params)}"
    sql += f" ORDER BY {order_sql}generated_at DESC LIMIT 1"
    async with pool.acquire() as conn:
        row = await conn.fetchrow(sql, *params)
    return _snapshot_pg_dict(row)


async def list_architecture_snapshots_pg(pool, project: str, limit: int = 30) -> list[dict]:
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT id, project, environment, status, model, prompt_version,
                   summary, source_count, evidence_coverage, generated_at,
                   published_at, created_by
            FROM architecture_snapshots
            WHERE project = $1
            ORDER BY generated_at DESC LIMIT $2
        """, project, limit)
    out = []
    for row in rows:
        item = dict(row)
        item['generated_at'] = _iso(item.get('generated_at'))
        item['published_at'] = _iso(item.get('published_at'))
        out.append(item)
    return out


async def publish_architecture_snapshot_pg(pool, project: str,
                                           snapshot_id: str) -> Optional[dict]:
    async with pool.acquire() as conn:
        async with conn.transaction():
            target = await conn.fetchrow("""
                SELECT environment FROM architecture_snapshots
                WHERE id = $1 AND project = $2 AND status = 'draft' FOR UPDATE
            """, snapshot_id, project)
            if not target:
                return None
            await conn.execute("""
                UPDATE architecture_snapshots SET status = 'archived'
                WHERE project = $1 AND environment = $2 AND status = 'published'
            """, project, target['environment'])
            row = await conn.fetchrow("""
                UPDATE architecture_snapshots
                SET status = 'published', published_at = NOW()
                WHERE id = $1 AND project = $2 RETURNING *
            """, snapshot_id, project)
    return _snapshot_pg_dict(row)


async def prune_architecture_snapshots_pg(pool, project: str,
                                          environment: str,
                                          keep_drafts: int) -> int:
    async with pool.acquire() as conn:
        result = await conn.execute("""
            DELETE FROM architecture_snapshots
            WHERE project = $1 AND environment = $2 AND status = 'draft'
              AND id NOT IN (
                  SELECT id FROM architecture_snapshots
                  WHERE project = $1 AND environment = $2 AND status = 'draft'
                  ORDER BY generated_at DESC LIMIT $3
              )
        """, project, environment, keep_drafts)
    return int(result.rsplit(' ', 1)[-1])


async def claim_architecture_generation_pg(pool, project: str,
                                           environment: str,
                                           local_run_date: str,
                                           source_digest: str,
                                           force: bool = False,
                                           lease_seconds: int = 900) -> dict:
    from datetime import date as _date
    import uuid as _uuid
    attempt_id = str(_uuid.uuid4())
    run_date = _date.fromisoformat(local_run_date)
    async with pool.acquire() as conn:
        async with conn.transaction():
            # Serializes even the first insert, where FOR UPDATE has no row.
            await conn.execute(
                "SELECT pg_advisory_xact_lock(hashtext($1))",
                f'{project}:{environment}')
            row = await conn.fetchrow("""
                SELECT local_run_date, status,
                       COALESCE(lease_expires_at > NOW(), FALSE) AS lease_active
                FROM architecture_generation_state
                WHERE project = $1 AND environment = $2
                FOR UPDATE
            """, project, environment)
            if row and row['status'] == 'running' and row['lease_active']:
                return {'claimed': False, 'reason': 'running'}
            if (row and str(row['local_run_date']) == local_run_date
                    and not force):
                return {'claimed': False, 'reason': 'daily_limit'}
            await conn.execute("""
                INSERT INTO architecture_generation_state
                    (project, environment, local_run_date, source_digest,
                     status, attempt_id, started_at, finished_at,
                     lease_expires_at, snapshot_id, last_error)
                VALUES ($1, $2, $3, $4, 'running', $5, NOW(), NULL,
                        NOW() + ($6 * INTERVAL '1 second'), NULL, NULL)
                ON CONFLICT(project, environment) DO UPDATE SET
                    local_run_date = EXCLUDED.local_run_date,
                    source_digest = EXCLUDED.source_digest,
                    status = 'running', attempt_id = EXCLUDED.attempt_id,
                    started_at = NOW(), finished_at = NULL,
                    lease_expires_at = EXCLUDED.lease_expires_at,
                    snapshot_id = NULL, last_error = NULL
            """, project, environment, run_date, source_digest,
                attempt_id, lease_seconds)
    return {'claimed': True, 'attempt_id': attempt_id}


async def finish_architecture_generation_pg(pool, project: str,
                                            environment: str,
                                            attempt_id: str, status: str,
                                            snapshot_id: str = None,
                                            error: str = None) -> bool:
    async with pool.acquire() as conn:
        result = await conn.execute("""
            UPDATE architecture_generation_state
            SET status = $1, finished_at = NOW(), lease_expires_at = NULL,
                snapshot_id = COALESCE($2, snapshot_id), last_error = $3
            WHERE project = $4 AND environment = $5 AND attempt_id = $6
        """, status, snapshot_id, error, project, environment, attempt_id)
    return result != 'UPDATE 0'


async def get_architecture_generation_state_pg(pool, project: str,
                                               environment: str) -> Optional[dict]:
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT project, environment, local_run_date, source_digest, status,
                   attempt_id, started_at, finished_at, lease_expires_at,
                   snapshot_id, last_error
            FROM architecture_generation_state
            WHERE project = $1 AND environment = $2
        """, project, environment)
    if not row:
        return None
    item = dict(row)
    item['local_run_date'] = str(item.get('local_run_date') or '')
    for key in ('started_at', 'finished_at', 'lease_expires_at'):
        item[key] = _iso(item.get(key))
    return item


async def set_architecture_run_state_pg(pool, project: str, status: str,
                                        snapshot_id: str = None,
                                        error: str = None) -> None:
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO architecture_project_state
                (project, last_run_at, last_status, last_error, last_snapshot_id)
            VALUES ($1, NOW(), $2, $3, $4)
            ON CONFLICT(project) DO UPDATE SET
                last_run_at = NOW(), last_status = EXCLUDED.last_status,
                last_error = EXCLUDED.last_error,
                last_snapshot_id = COALESCE(EXCLUDED.last_snapshot_id,
                                            architecture_project_state.last_snapshot_id)
        """, project, status, error, snapshot_id)


async def get_architecture_run_state_pg(pool, project: str) -> Optional[dict]:
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT project, last_run_at, last_status, last_error, last_snapshot_id
            FROM architecture_project_state WHERE project = $1
        """, project)
    if not row:
        return None
    item = dict(row)
    item['last_run_at'] = _iso(item.get('last_run_at'))
    return item
