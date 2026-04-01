# g:install_zikra

Install Zikra persistent memory on this machine. Follow every step in order.

## Step 1 — Check prerequisites

```bash
which git curl python3 docker docker-compose
```

If any are missing, install them before continuing.

## Step 2 — Clone the repo

```bash
git clone https://github.com/getzikra/zikra.git ~/zikra
cd ~/zikra
```

## Step 3 — Configure environment

```bash
cp .env.example .env
```

Edit `.env` and fill in:
- `POSTGRES_PASSWORD` — strong random password
- `N8N_BASIC_AUTH_PASSWORD` — strong random password
- `OPENAI_API_KEY` — your OpenAI key (required for semantic search)
- `ZIKRA_TOKEN` — a secret token you choose (e.g. `openssl rand -hex 32`)
- `WEBHOOK_URL` — your public n8n URL (e.g. `https://n8n.yourdomain.com/`)

## Step 4 — Start the stack

```bash
docker-compose up -d
```

Wait for both containers to be healthy:
```bash
docker-compose ps
```

Both `zikra_postgres` and `zikra_n8n` should show `healthy` or `Up`.

## Step 5 — Import the Zikra workflow into n8n

1. Open n8n at `http://localhost:5678` (or your public URL)
2. Log in with your `N8N_BASIC_AUTH_USER` / `N8N_BASIC_AUTH_PASSWORD`
3. Go to **Workflows → Import from file**
4. Select `workflow/zikra_mcp_router.json`
5. Click **Activate** to enable the workflow

## Step 6 — Install Claude Code hooks

```bash
bash install.sh
```

The installer will:
- Copy `hooks/zikra_autolog.sh` to `~/.claude/hooks/`
- Copy `context/CLAUDE.md` to `~/.claude/CLAUDE.md` (or append to existing)
- Set your `ZIKRA_TOKEN` and webhook URL in both files
- Make the hook executable

## Step 7 — Verify

```bash
curl -s -X POST "http://localhost:5678/webhook/zikra" \
  -H "Authorization: Bearer YOUR_ZIKRA_TOKEN" \
  -H "Content-Type: application/json" \
  -H "User-Agent: curl/7.81.0" \
  -d '{"command":"search","query":"test","project":"global"}'
```

Expected response: `{"results":[],"count":0,...}`

## Step 8 — Save this install to memory

```bash
curl -s -X POST "http://localhost:5678/webhook/zikra" \
  -H "Authorization: Bearer YOUR_ZIKRA_TOKEN" \
  -H "Content-Type: application/json" \
  -H "User-Agent: curl/7.81.0" \
  -d '{
    "command":     "save_memory",
    "project":     "zikra",
    "memory_type": "decision",
    "title":       "zikra installed on '"$(hostname -s)"'",
    "content_md":  "Zikra installed and verified working. Webhook: http://localhost:5678/webhook/zikra",
    "tags":        null,
    "created_by":  "'"$(hostname -s)"'"
  }'
```

Installation complete.
