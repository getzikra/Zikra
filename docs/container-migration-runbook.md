# Container migration and operations runbook

This runbook operates the accepted stack in [ADR 0001](adr/0001-containerized-postgres-litellm.md). Database archives contain private memory content and access tokens. Never publish them or print row content.

## Prerequisites

- Docker with Compose support
- 1Password CLI signed into `a3tai.1password.com`
- A private, mode-`0600` `config/zikra-secrets.op` containing only these variable references:
  - `ZIKRA_OWNER_TOKEN`
  - `ZIKRA_POSTGRES_PASSWORD`
  - `OPENAI_API_KEY`
  - `LITELLM_MASTER_KEY`

The concrete reference file is ignored by Git. Resolve it only through `scripts/stack.sh`.

## Routine operation

```bash
./scripts/stack.sh up -d --build
./scripts/stack.sh ps
./scripts/stack.sh logs --tail 100 zikra postgres litellm
./scripts/stack.sh down
```

Only Zikra publishes a port, at `127.0.0.1:8377`.

## SQLite-to-PostgreSQL cutover

1. Rehearse against a disposable Compose project and volume.
2. Stop the SQLite API to freeze writes.
3. Use SQLite's backup API to create a standalone database in a private backup directory.
4. Run `PRAGMA integrity_check` against the backup and record its approved SHA-256 checksum (for example, `shasum -a 256 /absolute/private/path/zikra.db`).
5. Archive the source image identity or image tar needed for rollback.
6. Start only PostgreSQL and LiteLLM:

   ```bash
   ./scripts/stack.sh up -d postgres litellm
   ```

7. Import the standalone backup into the empty PostgreSQL volume:

   ```bash
   ZIKRA_SQLITE_SNAPSHOT=/absolute/private/path/zikra.db \
   ZIKRA_SQLITE_SHA256=<approved-64-character-digest> \
     ./scripts/stack.sh --profile tools run --rm migrate
   ```

8. Start Zikra and wait for all health checks:

   ```bash
   ./scripts/stack.sh up -d zikra
   ./scripts/stack.sh ps
   ```

9. Verify owner and developer authentication, an MCP initialize request, keyword retrieval, LiteLLM-backed semantic retrieval, row counts, and 1536-dimensional vectors without printing credentials or memory bodies.
10. Create a PostgreSQL custom-format dump and retain the SQLite source archive according to the approved retention policy.

The migrator refuses a non-empty destination. It imports all tables in one transaction and verifies counts, identifiers, row content, and embedding bytes before commit.

## PostgreSQL backup

Use the running database container and write the archive to a private host directory:

```bash
umask 077
./scripts/stack.sh exec -T postgres \
  pg_dump -U zikra -d zikra -Fc > /absolute/private/path/zikra-postgres.dump
```

Verify the archive is readable without restoring it:

```bash
./scripts/stack.sh exec -T postgres pg_restore -l < /absolute/private/path/zikra-postgres.dump >/dev/null
```

## Rollback

Rollback is destructive with respect to writes made after cutover.

1. Stop the PostgreSQL-backed Zikra API.
2. Take a final PostgreSQL dump for forensic recovery.
3. Verify the archived SQLite checksum.
4. Restore the archived source image and run it against a writable copy of the archived SQLite database on `127.0.0.1:8377`.
5. Resolve the owner and provider credentials from 1Password; do not restore a plaintext environment file.
6. Verify owner and developer authentication before reconnecting clients.

Do not modify the immutable archive directly. Always make a writable rollback copy.

## Upgrade policy

Image references are digest-pinned. For an upgrade:

1. review upstream release notes and advisories;
2. update the tag and digest together;
3. build and run the migration/API rehearsal against a disposable volume;
4. take a PostgreSQL custom-format dump;
5. upgrade one service at a time and verify health and authentication.
