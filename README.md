# Zikra — Shared Memory Across Every AI Tool Your Team Uses

> Persistent memory for Claude Code, Cursor, Gemini CLI, and other AI coding agents — shared across sessions and machines.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![MCP](https://img.shields.io/badge/MCP-native-blue)](https://modelcontextprotocol.io/)

**Website:** [zikra.dev](https://zikra.dev) · Self-hosted · Agent-agnostic · MCP native

```
zikra 17 runs · 847 memories │ you@team-server │ Sonnet 4.6 │ ~/project (main) │ 387K/200K ████░░░░░░ 45%
```

---

AI agents have no memory between sessions. Claude Code forgets your architecture decisions overnight. Gemini CLI has no idea what Claude Web researched this morning. Cursor on your teammate's machine has never seen your decisions.

Zikra fixes that. It's a **MCP-native memory server** that all your agents connect to. Every decision, requirement, error, and session summary — saved, searchable, and shared across every tool and every machine.

— Mukarram

---

## Getting Started

### Step 1 — Install the server

```bash
git clone https://github.com/getzikra/zikra
cd zikra
python3 -m venv .venv
source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -e .
python3 installer.py         # interactive setup, ~2 minutes
python3 -m zikra
```

The installer creates a `.env` file and generates your admin token. The server binds to `http://localhost:8000` by default. `python3 -m zikra` must be run from the same directory as your `.env` file.

> To reach it from other machines, run `cloudflared tunnel --url http://localhost:8000` (free, gives you a permanent public URL like `https://zikra.yourteam.com`).

### Step 2 — Enable MCP in Claude Code

Open **Claude Code → Settings → MCP → Add Server** and paste:

```json
{
  "mcpServers": {
    "zikra": {
      "url": "http://your-server:8000/mcp",
      "headers": { "Authorization": "Bearer YOUR_ZIKRA_TOKEN" }
    }
  }
}
```

The installer does this automatically when run locally. For remote servers, paste your public URL instead of `localhost:8000`.

### Step 3 — Onboard Claude Code (hooks + statusline)

Paste this into any Claude Code session:

```
Fetch https://raw.githubusercontent.com/GetZikra/zikra/main/prompts/g_zikra.md
and follow every instruction in it.
```

This installs the **Stop hook** (auto-saves every session), **PreCompact hook**, and the live **statusline bar** showing run counts and memory stats. Claude Code will ask for your server URL and token, then configure everything automatically.

---

## Updating Zikra

**Server** — pull latest and restart:

```bash
git pull origin main
pip install -e .
python3 -m zikra   # or restart your service
```

**Claude Code hooks** — re-run the same onboarding prompt:

```
Fetch https://raw.githubusercontent.com/GetZikra/zikra/main/prompts/g_zikra.md
and follow every instruction in it.
```

The prompt detects your existing install and only refreshes what changed. Your token and config are preserved. The MCP server in Claude Code settings never needs to be updated manually — it reads from your server dynamically.

---

## Profiles

| Profile | Storage | Hooks | Extra deps |
|---------|---------|-------|------------|
| Webhook (default) | SQLite | none | none |
| Auto-log | SQLite | session hooks | none |
| Full | SQLite or Postgres | hooks + daemon | asyncpg (Postgres only) |

---

## Environment variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `ZIKRA_TOKEN` | Yes | generated | Bearer token for the API |
| `OPENAI_API_KEY` | No | — | Enables semantic search. Keyword-only if absent. |
| `DB_BACKEND` | No | `sqlite` | `sqlite` or `postgres` |
| `DB_HOST` | Postgres only | `localhost` | |
| `DB_PORT` | Postgres only | `5432` | |
| `DB_NAME` | Postgres only | — | |
| `DB_USER` | Postgres only | — | |
| `DB_PASSWORD` | Postgres only | — | |
| `ZIKRA_HOST` | No | `0.0.0.0` | Bind address |
| `ZIKRA_PORT` | No | `8000` | HTTP port |
| `ZIKRA_DB_PATH` | No | `./zikra.db` | SQLite database path |
| `ZIKRA_PROJECT` | No | `main` | Default project |
| `ZIKRA_SKIP_ONBOARDING` | No | — | Set to `1` for CI/scripted use |
| `OPENAI_API_BASE` | No | `https://api.openai.com/v1` | Swap for local or compatible embedding endpoint |
| `ZIKRA_EMBEDDING_MODEL` | No | `text-embedding-3-small` | Embedding model name |
| `ZIKRA_DECAY_DAYS` | No | `30` | Memory decay half-life in days (scoring) |
| `ZIKRA_FREQUENCY_WEIGHT` | No | `0.1` | Weight of access-frequency boost in scoring |

---

## Files written during install

| File | Description |
|---|---|
| `.env` | Credentials, written by installer |
| `zikra.db` | SQLite database (path from `ZIKRA_DB_PATH`, default `./zikra.db`) |
| `~/.zikra/token` | Saved bearer token |
| `~/.claude/settings.json` | MCP registration (merged, not overwritten) |
| `~/.claude/zikra_autolog.sh` | Session hook (autolog + full profiles only) |
| `~/.claude/notify.sh` | Notification hook (autolog + full profiles only) |
| `~/.claude/hooks/zikra-statusline.js` | Status line (autolog + full profiles only) |
| `~/.config/systemd/user/zikra.service` | Daemon unit (full profile, Linux only) |

---

## How results are ranked

Zikra does not return results in raw similarity order. Every search result passes through a scoring step that adjusts ranking based on:

- **Age** — recent memories rank higher. Half-life: 30 days. Floor: 0.05 (memories never disappear).
- **Access frequency** — frequently used prompts surface higher in search results (log scale).
- **Confidence** — memories saved with a lower `confidence_score` rank lower.

No configuration required. This works automatically on every search.

---

## Command reference

All commands are sent as `POST /webhook/zikra` with `Authorization: Bearer <token>`.

| Command | Aliases | Description |
|---|---|---|
| `search` | `find`, `query`, `recall`, `retrieve` | Hybrid semantic + keyword search |
| `save_memory` | `save`, `store`, `write` | Save a memory with embedding |
| `get_memory` | `fetch_memory`, `read_memory` | Retrieve memory by title or `id` |
| `get_prompt` | `fetch_prompt`, `run_prompt` | Retrieve a named prompt |
| `log_run` | `log_session`, `end_session` | Log a completed agent run |
| `log_error` | `log_bug`, `report_error` | Log an error or failure. Field: `message`, optional `context_md` |
| `save_requirement` | — | Save a project requirement |
| `save_prompt` | `write_prompt`, `store_prompt` | Save a prompt with semantic embedding |
| `list_prompts` | `get_prompts` | List prompts for a project |
| `list_requirements` | `list_reqs` | List requirements for a project |
| `promote_requirement` | `promote` | Change a requirement's memory_type (default: to prompt) |
| `create_token` | `new_token` | Generate a new bearer token (owner role required) |
| `get_schema` | `schema` | Return database DDL introspection (engine, tables, DDL) |
| `zikra_help` | `help` | Return full command reference with fields and aliases |
| `debug_protocol` | — | Return backend diagnostics: engine, memory count, key status |

**Roles:** `owner`, `admin`, `developer`, `viewer`

### Example request

```json
POST /webhook/zikra
Authorization: Bearer your-secret-token

{
  "command": "search",
  "project": "myapp",
  "query": "how does authentication work",
  "limit": 5
}
```

---

## PostgreSQL backend

For teams that need concurrent writes, set the following in your `.env`:

```
DB_BACKEND=postgres
DB_HOST=localhost
DB_PORT=5432
DB_NAME=ai_zikra
DB_USER=postgres
DB_PASSWORD=yourpassword
```

Install with Postgres support:

```bash
pip install -e ".[postgres]"
```

---

## Run tests

Requires a `.env` file with at minimum `ZIKRA_TOKEN` set.

```bash
OPENAI_API_KEY=sk-... python3 -m zikra.tests.test_all
```

---

## Notes on planned features

- Automated weekly cleanup and errors aging out in 30 days are **planned, not yet implemented**.

---

## License

MIT — see [LICENSE](LICENSE)

*Design in Claude Web. Execute in Claude Code. Share with your whole team.*
*Claude Web · Claude Code · Gemini Web · Gemini CLI · Codex · ChatGPT · any agent that can POST.*
