# g:update_zikra

Update Zikra to the latest version. Run this when a new release is available.

## Step 1 — Pull latest code

```bash
cd ~/zikra
git fetch origin
git status
```

Check for any local changes. If you have local changes to `.env`, `schema.sql`, or `docker-compose.yml`, stash them:

```bash
git stash
```

Then pull:

```bash
git pull origin main
```

Restore stash if needed:
```bash
git stash pop
```

## Step 2 — Check for schema migrations

```bash
ls migrations/
```

If there are new migration files (numbered higher than what you last ran), apply them in order:

```bash
# Example: apply migration 002
docker exec -i zikra_postgres psql -U zikra -d zikra \
  < migrations/002_whatever.sql
```

Always apply migrations in numeric order. Never skip one.

## Step 3 — Restart containers

```bash
docker-compose pull
docker-compose up -d --force-recreate
```

Wait for health:
```bash
docker-compose ps
```

## Step 4 — Re-import updated workflow (if workflow/ changed)

Check if the workflow JSON changed:
```bash
git diff HEAD~1 workflow/zikra_mcp_router.json | head -20
```

If it changed:
1. Open n8n at your instance URL
2. Go to the Zikra MCP Router workflow
3. Click the 3-dot menu → **Import from file**
4. Select `workflow/zikra_mcp_router.json`
5. Save and re-activate

## Step 5 — Re-run install.sh if hooks changed

```bash
git diff HEAD~1 hooks/ context/ | head -5
```

If hooks or context files changed:
```bash
bash install.sh
```

## Step 6 — Verify

```bash
curl -s -X POST "$ZIKRA_URL" \
  -H "Authorization: Bearer $ZIKRA_TOKEN" \
  -H "Content-Type: application/json" \
  -H "User-Agent: curl/7.81.0" \
  -d '{"command":"search","query":"test","project":"global"}'
```

## Step 7 — Save the update to memory

```bash
ZIKRA_VERSION="$(git rev-parse --short HEAD)"

curl -s -X POST "$ZIKRA_URL" \
  -H "Authorization: Bearer $ZIKRA_TOKEN" \
  -H "Content-Type: application/json" \
  -H "User-Agent: curl/7.81.0" \
  -d '{
    "command":     "save_memory",
    "project":     "zikra",
    "memory_type": "decision",
    "title":       "zikra updated to '"$ZIKRA_VERSION"' on '"$(hostname -s)"'",
    "content_md":  "Pulled latest from main, applied migrations if any, restarted containers, verified webhook responding.",
    "tags":        null,
    "created_by":  "'"$(hostname -s)"'"
  }'
```

Update complete.
