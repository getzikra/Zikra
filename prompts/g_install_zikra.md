# g:install_zikra
# First time install on any machine

You are installing Zikra. Follow every step in order.
Do not skip any step. Do not ask questions until told to.

## Step 1 — Fetch latest install scripts from GitHub

curl -fsSL https://raw.githubusercontent.com/getzikra/zikra/main/hooks/zikra_autolog.sh -o /tmp/zikra_autolog.sh
curl -fsSL https://raw.githubusercontent.com/getzikra/zikra/main/context/CLAUDE.md -o /tmp/CLAUDE.md

## Step 2 — Ask the user these 3 questions

1. Which version are you installing?
   - (A) Zikra Lite — no Docker, no Postgres, pip install
   - (B) Zikra Full — n8n + Postgres + Docker

2. What is your ZIKRA_TOKEN?
   (This is your personal Bearer token for auth)

3. What is your Zikra server URL?
   - Lite default: http://localhost:7723
   - Full default: https://n8n.yourserver.com/webhook/zikra

## Step 3 — Install hooks

mkdir -p ~/.claude
cp /tmp/zikra_autolog.sh ~/.claude/zikra_autolog.sh
chmod +x ~/.claude/zikra_autolog.sh
cp /tmp/CLAUDE.md ~/.claude/CLAUDE.md

## Step 4 — Write MCP config to ~/.claude/settings.json

Write the following to ~/.claude/settings.json using the
URL and token the user provided in Step 2:

{
  "mcpServers": {
    "zikra": {
      "url": "<USER_URL>/mcp/sse",
      "env": {
        "ZIKRA_TOKEN": "<USER_TOKEN>"
      }
    }
  },
  "hooks": {
    "Stop": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "bash ~/.claude/zikra_autolog.sh"
          }
        ]
      }
    ]
  }
}

## Step 5 — Install the correct backend

If user chose Lite:
  pip install zikra-lite --break-system-packages
  echo "OPENAI_API_KEY=<ask user>" >> ~/.zikra.env
  echo "ZIKRA_TOKEN=<user token>" >> ~/.zikra.env
  echo "ZIKRA_PORT=7723" >> ~/.zikra.env

If user chose Full:
  echo "Zikra Full requires Docker. Run: docker compose up -d"
  echo "Then import workflow from zikra/workflow/zikra_mcp_router.json into n8n"

## Step 6 — Test the connection

Run a test search to confirm Zikra is reachable:

curl -s -X POST <USER_URL>/webhook/zikra \
  -H "Authorization: Bearer <USER_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"command":"search","query":"test","project":"global","max_results":1}'

If response contains results or empty array: SUCCESS
If response contains error or connection refused: FAIL — report the error

## Step 7 — Confirm to user

Print:
  Zikra installed successfully.
  Version: <lite or full>
  Server: <url>
  Hooks: ~/.claude/zikra_autolog.sh
  MCP config: ~/.claude/settings.json
  
  Start a new Claude Code session to activate the hooks.
  Next session just say: run g:sync_zikra
