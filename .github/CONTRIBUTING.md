# Contributing to Zikra

Thank you for your interest in contributing. Zikra is a team-focused persistent memory server built on PostgreSQL, pgvector, and n8n. This guide covers everything you need to get a local dev environment running and submit a pull request.

## Getting started

Look for issues labelled `good first issue` to get started.

## Prerequisites

- PostgreSQL with the `pgvector` extension
- n8n (self-hosted or the Docker Compose setup below)
- Python 3.11+
- Node.js v18+ (required for the `--full` statusline profile)
- `curl` and `python3` available in your PATH

## Setting up local dev

**Step 1 — Clone the repo**

```bash
git clone https://github.com/getzikra/zikra.git
cd zikra
```

**Step 2 — Start PostgreSQL and n8n via Docker Compose**

This is the recommended approach. It starts a pre-configured PostgreSQL (with pgvector) and n8n instance.

```bash
cp .env.example .env   # then edit .env with your credentials
docker compose up -d
```

Verify both services are up:

```bash
docker compose ps
docker compose logs n8n --tail=20
```

**Step 3 — Apply the schema**

If you used Docker Compose, the schema is applied automatically. For a manual setup:

```bash
psql -h localhost -U zikra -d zikra -f schema.sql
```

Verify:

```bash
docker exec -it zikra_postgres psql -U zikra -d zikra -c "\dt zikra.*"
```

**Step 4 — Import and activate the n8n workflow**

1. Open n8n at `http://localhost:5678`
2. Go to Workflows > Import from file
3. Select `workflow/zikra_mcp_router.json`
4. Configure the PostgreSQL and OpenAI credentials in the workflow nodes
5. Activate the workflow using the toggle at the top of the editor

**Step 5 — Create a bearer token**

```sql
-- In psql:
INSERT INTO zikra.access_tokens (token, label, role)
VALUES ('dev-' || gen_random_uuid()::text, 'dev token', 'writer')
RETURNING token;
```

**Step 6 — Verify the webhook is working**

```bash
curl -s -X POST "http://localhost:5678/webhook/zikra" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -H "User-Agent: curl/7.81.0" \
  -d '{"command":"search","query":"test","project":"dev","max_results":1}'
```

An empty `{"results": [], "count": 0}` response confirms the stack is working.

**Step 7 — Onboard Claude Code (optional)**

Paste this into any Claude Code session to install hooks and the statusline:

```
Fetch https://raw.githubusercontent.com/getzikra/zikra/main/prompts/g_zikra.md
and follow every instruction in it.
```

## Running tests

There is no standalone test suite — Zikra's logic lives in the n8n workflow. To test changes to the workflow, activate it in n8n and verify the webhook manually as shown above.

For schema migration changes, apply them against a local database and verify the table structure:

```bash
psql -h localhost -U zikra -d zikra -c "\dt zikra.*"
psql -h localhost -U zikra -d zikra -c "\d zikra.memories"
```

For hook and script changes in `hooks/` or `bin/`, run them directly and check their output in a Claude Code session.

## Making changes

- **n8n workflow changes** — export the updated workflow from n8n and replace `workflow/zikra_mcp_router.json`. Include a summary of which nodes changed in your PR description.
- **Schema changes** — add a new migration file under `migrations/` (e.g. `002_your_change.sql`). Do not edit `001_initial_schema.sql`.
- **Hook changes** — hooks live in `hooks/`. Test them manually before submitting.
- **Documentation** — docs live in `docs/`. Keep them in sync with any behaviour changes.

## PR process

1. Fork the repo and create a branch from `main`: `git checkout -b your-feature-name`
2. Make your changes with clear, focused commits
3. Open a pull request against `main`
4. Describe what the PR changes and why — include steps to verify it works
5. A maintainer will review and may request changes
6. Once approved, it will be merged

Keep PRs focused. A PR that changes one thing is easier to review than one that changes five.

## Reporting bugs

Open a GitHub issue using the Bug Report template. Include logs from `docker compose logs n8n --tail=50` and the exact request that triggered the error if applicable. See [SECURITY.md](SECURITY.md) for vulnerabilities — do not open public issues for those.

## Questions

If you are unsure whether your idea is in scope, open a Feature Request issue first and describe what you want to build.
