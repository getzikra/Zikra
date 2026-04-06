VERSION = 1
DESCRIPTION = "initial schema: memories, prompt_runs, error_log, access_tokens"

SQL = """
CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    project TEXT NOT NULL DEFAULT 'global',
    module TEXT,
    memory_type TEXT NOT NULL DEFAULT 'conversation',
    title TEXT NOT NULL,
    content_md TEXT NOT NULL DEFAULT '',
    tags TEXT NOT NULL DEFAULT '[]',
    resolution TEXT,
    created_by TEXT,
    confidence_score REAL DEFAULT 1.0,
    access_count INTEGER DEFAULT 0,
    searchable INTEGER DEFAULT 1,
    resolved INTEGER DEFAULT 0,
    pending_review INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_memories_title_type_project
    ON memories(title, memory_type, project);

CREATE INDEX IF NOT EXISTS idx_memories_project
    ON memories(project, memory_type);

CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
    title,
    content_md,
    content=memories,
    content_rowid=rowid
);

CREATE VIRTUAL TABLE IF NOT EXISTS memories_vec USING vec0(
    embedding float[1536]
);

CREATE TABLE IF NOT EXISTS prompt_runs (
    id TEXT PRIMARY KEY,
    project TEXT,
    runner TEXT,
    prompt_name TEXT,
    status TEXT DEFAULT 'success',
    output_summary TEXT,
    tokens_input INTEGER,
    tokens_output INTEGER,
    cost_usd REAL,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS error_log (
    id TEXT PRIMARY KEY,
    project TEXT,
    runner TEXT,
    error_type TEXT,
    message TEXT,
    stack_trace TEXT,
    context_md TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS access_tokens (
    id TEXT PRIMARY KEY,
    token TEXT NOT NULL UNIQUE,
    person_name TEXT,
    role TEXT DEFAULT 'owner',
    active INTEGER DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now'))
);
"""
