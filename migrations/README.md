# Migrations

This folder contains incremental SQL migrations that define the Zikra database schema over time.

## What this folder is for

Each file in this folder applies one change to the database — adding a table, adding a column, creating an index, etc. Migrations run in order and are tracked in the `schema_versions` table so they are never applied twice.

## Naming convention

```
NNN_description.sql
```

- `NNN` — zero-padded sequence number (001, 002, 003, ...)
- `description` — short snake_case description of what the migration does

Examples:
```
001_initial_schema.sql
002_add_schema_versions_table.sql
003_add_token_personas.sql
```

## How to run

```bash
bash scripts/migrate.sh
```

This applies all pending migrations in order and updates `schema.sql` to reflect the current state.

## Rules

- **Never edit existing migration files.** Migrations are append-only. Once a migration has run on any machine, it must not change.
- **Always add new migrations** — never modify `schema.sql` directly.
- Each migration should be idempotent where possible (`CREATE TABLE IF NOT EXISTS`, `ADD COLUMN IF NOT EXISTS`).
- Wrap destructive operations in a transaction so a failure doesn't leave the schema in a partial state.

## Current migrations

| File | Description |
|------|-------------|
| `001_initial_schema.sql` | Initial tables: memories, tokens, prompts, runs, errors |
| `002_add_schema_versions_table.sql` | Add schema_versions table for migration tracking |
