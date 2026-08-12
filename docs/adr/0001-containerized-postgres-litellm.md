# ADR 0001: Run the local Zikra stack with PostgreSQL and LiteLLM

- **Status:** Accepted
- **Date:** 2026-08-12

## Context and problem statement

The local deployment ran the Zikra API in a container but stored its state in a host-bind-mounted SQLite database. SQLite is appropriate for a single process, but it leaves the database outside the container stack and limits concurrent writes. Embedding and distillation requests also went directly from Zikra to the model provider. The repository's former `docker-compose.yml` described a legacy n8n stack and did not run the current API.

The cutover must preserve every current business table, access token, timestamp, relationship, retrieval record, prompt run, and 1536-dimensional embedding. It must also retain an independently verifiable SQLite rollback artifact indefinitely.

## Decision drivers

- Containerize the API, database, and model gateway as one operated stack.
- Preserve all SQLite data and existing client identities.
- Keep the API localhost-only and the database unexposed.
- Keep provider, database, owner, and gateway credentials out of Compose files and container configuration environments.
- Support a deterministic rehearsal, brief write freeze, verified cutover, and rollback.
- Avoid restoring the unrelated legacy n8n workflow stack.

## Considered options

1. Keep SQLite on a bind mount.
2. Run Zikra with PostgreSQL/pgvector.
3. Run Zikra with PostgreSQL/pgvector and an internal LiteLLM gateway.
4. Restore the legacy PostgreSQL, n8n, and LiteLLM stack.

## Decision outcome

Run three services under Docker Compose:

- `zikra`: the current API, built with the PostgreSQL extra and run as a non-root user;
- `postgres`: exact-digest-pinned PostgreSQL 16 with pgvector on an internal network and named volume;
- `litellm`: exact-digest-pinned LiteLLM with no host port, routing the existing embedding and distillation models.

Only `127.0.0.1:8377` is published. PostgreSQL has no host port. LiteLLM has no host port. Zikra reaches PostgreSQL on an internal database network and LiteLLM on the application network.

Secrets are resolved command-scoped from 1Password by `scripts/stack.sh`. Compose environment-backed secrets become files under `/run/secrets`; they are not placed in service environment declarations or committed files. The local secret-reference file is mode `0600` and ignored by Git.

The migration uses `scripts/migrate_sqlite_to_postgres.py`. It requires a standalone SQLite backup and its separately approved SHA-256 digest, performs an integrity and exact-schema check, imports into an empty PostgreSQL database in one transaction, and verifies table counts, primary/composite identifiers, all non-vector row content, embedding dimensions, and exact float32 embedding bytes. PostgreSQL stores embeddings as `vector(1536)` rather than `halfvec(3072)` so the current SQLite float32 vectors and default embedding model retain their dimension and precision.

Cutover uses a brief write freeze. The final SQLite snapshot, checksum, source image archive, and rollback metadata are retained indefinitely under the user's private Zikra backup directory.

## Consequences

### Positive

- Database lifecycle, health checks, and persistence are managed by Compose.
- PostgreSQL supports concurrent writers and pgvector indexing.
- Provider access is centralized behind an internal LiteLLM endpoint.
- The migration is repeatable and fails closed on unauthenticated snapshots, source-schema drift, occupied destinations, or content drift.
- The API fails closed until the migrator commits a verified import marker.
- Existing owner and developer identities continue to work after migration.

### Negative

- Local operation now requires Docker, 1Password CLI access, and three services.
- Environment-backed Compose secrets require writable container layers in the current OrbStack implementation; capability dropping, non-root API execution, no-new-privileges, tmpfs scratch space, and network isolation remain enabled.
- LiteLLM and PostgreSQL upgrades must be deliberate because images are digest-pinned.
- Rollback after new PostgreSQL writes requires accepting loss of post-cutover writes or performing a reverse migration.

### Neutral

- The archived SQLite database remains the rollback source but is no longer live.
- n8n is not part of the core Zikra runtime.

## Security and operational considerations

- Never print, commit, or persist resolved secret values.
- Run Compose only through `scripts/stack.sh` or an equivalent command-scoped `op run` invocation.
- Keep the API bound to loopback and do not publish PostgreSQL or LiteLLM ports.
- Treat database archives as sensitive because they contain memory content and access tokens.
- Verify checksums before rollback and take a PostgreSQL dump before upgrades.
- A PostgreSQL custom-format dump is untrusted executable database input unless its source is trusted.

## Implementation evidence

- `docker-compose.yml`
- `Dockerfile`
- `litellm-config.yaml`
- `scripts/stack.sh`
- `scripts/container-entrypoint.sh`
- `scripts/litellm-entrypoint.sh`
- `scripts/migrate_sqlite_to_postgres.py`
- `zikra/tests/test_sqlite_postgres_migration.py`
- `zikra/tests/test_mcp_runtime_compat.py`
- `docs/container-migration-runbook.md`
