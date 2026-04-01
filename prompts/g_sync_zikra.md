# g:sync_zikra
# Run at the start of every session

You are syncing Zikra for this session. Do all steps silently
unless something fails.

## Step 1 — Fetch latest version of this prompt from GitHub

curl -fsSL https://raw.githubusercontent.com/getzikra/zikra/main/prompts/g_sync_zikra.md -o /tmp/g_sync_zikra_latest.md

Compare /tmp/g_sync_zikra_latest.md to this file.
If different, tell the user: "Zikra sync prompt updated — 
using latest version" then follow the latest version instead.

## Step 2 — Fetch and update hooks silently

curl -fsSL https://raw.githubusercontent.com/getzikra/zikra/main/hooks/zikra_autolog.sh -o ~/.claude/zikra_autolog.sh
chmod +x ~/.claude/zikra_autolog.sh

## Step 3 — Check settings.json exists

If ~/.claude/settings.json does not exist or has no mcpServers:
  Tell user: "Zikra not configured on this machine. 
  Please run g:install_zikra first."
  Stop here.

## Step 4 — Read token and URL from settings.json

Extract ZIKRA_TOKEN and url from ~/.claude/settings.json

## Step 5 — Test connection

curl -s -X POST <URL>/webhook/zikra \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"command":"search","query":"zikra","project":"global","max_results":1}'

If success: print "Zikra connected. Ready."
If fail: print "Zikra unreachable at <URL> — is the server running?"
