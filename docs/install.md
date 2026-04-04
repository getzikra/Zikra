# Zikra Install Guide

## Prerequisites checklist

Before running the installer, you need:

- [ ] [Claude Code](https://docs.anthropic.com/en/docs/claude-code) installed and working (`claude --version`)
- [ ] [Docker](https://docs.docker.com/get-docker/) + [Docker Compose v2](https://docs.docker.com/compose/install/) — required for the recommended install
- [ ] A running PostgreSQL instance with the `pgvector` extension
- [ ] A running n8n instance (self-hosted)
- [ ] The Zikra n8n workflow imported and active
- [ ] `curl` available on every agent machine
- [ ] `python3` available on every agent machine
- [ ] `node` (v18+) — only required for `--full` profile statusline

---

## Option A: Docker Compose (recommended)

This sets up both PostgreSQL and n8n in containers with everything pre-configured.

### Step 1: Clone the repository

```bash
git clone https://github.com/getzikra/zikra.git
cd zikra
```

### Step 2: Create your .env file

```bash
cp docker-compose.yml docker-compose.yml.bak   # optional backup

cat > .env <<EOF
POSTGRES_USER=zikra
POSTGRES_PASSWORD=$(openssl rand -base64 24)
POSTGRES_DB=zikra

N8N_BASIC_AUTH_ACTIVE=true
N8N_BASIC_AUTH_USER=admin
N8N_BASIC_AUTH_PASSWORD=$(openssl rand -base64 24)

WEBHOOK_URL=https://n8n.yourdomain.com/
N8N_HOST=n8n.yourdomain.com
N8N_PROTOCOL=https
N8N_PORT=5678

N8N_ENCRYPTION_KEY=$(openssl rand -hex 16)
EOF
```

> Keep this .env file secure — it contains your database password.

### Step 3: Start the services

```bash
docker compose up -d
```

PostgreSQL starts first (with pgvector). n8n waits for Postgres to be healthy
before starting (typically 15–30 seconds).

### Step 4: Verify both services are running

```bash
docker compose ps
# Both zikra_postgres and zikra_n8n should show "Up" status

docker compose logs n8n --tail=20
# Should show "Editor is now accessible via: http://localhost:5678"
```

### Step 5: Verify the schema was applied

```bash
docker exec -it zikra_postgres psql -U zikra -d zikra -c "\dt zikra.*"
```

Expected output:
```
          List of relations
 Schema |     Name      | Type  | Owner
--------+---------------+-------+-------
 zikra  | access_tokens | table | zikra
 zikra  | active_runs   | table | zikra
 zikra  | memories      | table | zikra
 zikra  | prompt_runs   | table | zikra
 zikra  | token_projects| table | zikra
```

---

## Option B: Existing PostgreSQL and n8n

Use this if you already have PostgreSQL and n8n running.

### Step 1: Apply the schema

```bash
psql -h your-postgres-host -U your-user -d your-db -f schema.sql
```

Or use the migration:

```bash
psql -h your-postgres-host -U your-user -d your-db -f migrations/001_initial_schema.sql
```

### Step 2: Verify pgvector is available

```bash
psql -h your-postgres-host -U your-user -d your-db \
  -c "SELECT extname FROM pg_extension WHERE extname='vector';"
```

If it returns no rows, install pgvector:

```bash
# Ubuntu/Debian
apt install postgresql-16-pgvector

# macOS (Homebrew)
brew install pgvector

# Then in psql:
CREATE EXTENSION IF NOT EXISTS vector;
```

---

## Importing the n8n workflow

### Step 1: Open n8n

Navigate to `http://localhost:5678` (or your n8n URL) and log in.

### Step 2: Import the workflow

1. Click **Workflows** → **Import from file**
2. Select the Zikra workflow JSON (available at zikra.dev/workflow.json)
3. Click **Import**

### Step 3: Configure credentials

In the workflow, update the PostgreSQL node credentials:
- Host: `postgres` (if using Docker Compose) or your Postgres hostname
- Database: `zikra`
- User: your Postgres user
- Password: your Postgres password

For the OpenAI embedding node, add your OpenAI API key.

### Step 4: Activate the workflow

Click the toggle at the top of the workflow editor to set it to **Active**.

### Step 5: Get your webhook URL

The webhook URL will be shown in the workflow trigger node. It looks like:
```
https://n8n.yourdomain.com/webhook/zikra
```

Note this URL — you will need it during install.sh.

---

## Running install.sh

### Step 0: Generate your bearer token

Before running install.sh you need a bearer token. Generate one now:

```bash
openssl rand -hex 16
# example output: 4f3a9b2c1d8e7f6a5b4c3d2e1f0a9b8c
```

Copy the output — you will paste it when install.sh prompts for your token.

### Run the installer

On each agent machine:

```bash
# Quickest method — pipe to bash (review the script first if you prefer)
curl -fsSL https://zikra.dev/install.sh | bash

# Or choose a profile explicitly:
curl -fsSL https://zikra.dev/install.sh | bash -s -- --minimal
curl -fsSL https://zikra.dev/install.sh | bash -s -- --standard
curl -fsSL https://zikra.dev/install.sh | bash -s -- --full
```

**Manual alternative** (inspect before running):
```bash
curl -fsSL https://zikra.dev/install.sh -o /tmp/zikra_install.sh
# Review the file before executing:
less /tmp/zikra_install.sh
bash /tmp/zikra_install.sh
```

When prompted:
1. **Webhook URL** — paste your n8n webhook URL (e.g. `https://n8n.example.com/webhook/zikra`)
2. **Bearer token** — paste the token you generated in Step 0
3. **Default project** — a short lowercase name (e.g. `myproject`)

### Creating your first bearer token

Before running install.sh, create a token via the admin interface or directly
in the database:

```sql
-- In psql (Zikra Full — uses `label` column):
INSERT INTO zikra.access_tokens (token, label, role)
VALUES ('myproject-' || gen_random_uuid()::text, 'main token', 'writer')
RETURNING token;
```

> **Column name note:** Zikra Full (PostgreSQL) uses `label` to identify token owners.
> Zikra Lite (SQLite) uses `person_name` instead. These are functionally equivalent
> but the column names differ — be aware when writing raw SQL against either backend.

Copy the returned token value — this is your bearer token.

---

## Verifying the install

After install.sh completes, run a test curl:

```bash
curl -s -X POST "https://n8n.yourdomain.com/webhook/zikra" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -H "User-Agent: curl/7.81.0" \
  -d '{"command":"search","query":"test","project":"myproject","max_results":1}'
```

Expected response:
```json
{"results": [], "count": 0}
```

An empty results array is correct for a fresh install. A 200 status with JSON
confirms the webhook is working.

---

## Common errors and fixes

### HTTP 401 Unauthorized

- Check your bearer token is correct
- Verify the token exists in `zikra.access_tokens` and `active = true`
- Make sure you're including `Authorization: Bearer <token>` (not `Bearer: <token>`)

### HTTP 404 Not Found

- The workflow is not active in n8n
- The webhook URL path is wrong — check it ends with `/webhook/zikra` (no trailing slash needed)

### HTTP 500 Internal Server Error

- PostgreSQL connection from n8n is failing — check credentials and host
- pgvector extension is not installed — run `CREATE EXTENSION IF NOT EXISTS vector;`
- The memories table doesn't exist — apply schema.sql

### `curl: (6) Could not resolve host`

- DNS issue or wrong hostname in the webhook URL
- If using Docker Compose locally, use `http://localhost:5678/webhook/zikra`

### Diary not saving after session end

- Confirm the Stop hook is wired: `cat ~/.claude/settings.json | python3 -m json.tool | grep -A5 Stop`
- Verify `claude` CLI is available in PATH from a non-interactive shell
- Check `/tmp/zikra_last_diary` timestamp — delete it to force a new diary

### zikra_watcher.py not starting (--full profile)

- Check systemd: `systemctl --user status zikra-watcher`
- View logs: `journalctl --user -u zikra-watcher -n 50`
- Start manually: `python3 ~/.claude/zikra_watcher.py`

### Statusline not showing

- Confirm `statusLine` is in settings.json: `cat ~/.claude/settings.json | grep statusLine`
- Make sure `~/.claude/hooks/zikra-statusline.js` is executable: `chmod +x ~/.claude/hooks/zikra-statusline.js`
- Test it: `echo '{}' | node ~/.claude/hooks/zikra-statusline.js`
- Restart Claude Code after settings.json changes
