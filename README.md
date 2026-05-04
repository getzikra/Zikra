# Zikra — Team Memory for AI Agents

> Not just session memory. A shared, governed memory layer for every agent, every person, and every project your team runs.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![MCP](https://img.shields.io/badge/MCP-native-blue)](https://modelcontextprotocol.io/)
[![MCP Server](https://glama.ai/mcp/servers/getzikra/zikra/badges/score.svg)](https://glama.ai/mcp/servers/getzikra/zikra)

**Website:** [zikra.dev](https://zikra.dev) · Self-hosted · MIT · Scales to millions of memories

**Architecture:** [Governed project memory for teams of agents](docs/architecture.md)

**Promotion kit:** [submission copy, launch posts, and directory targets](PROMOTION.md)

```
zikra 17 runs · 847 memories │ you@team-server │ Sonnet 4.6 │ ~/project (main) │ 387K/200K ████░░░░░░ 45%
```

---

## Install in one line

```bash
claude mcp add zikra http://localhost:8000/mcp --header "Authorization: Bearer YOUR_TOKEN"
```

Or add to `~/.claude/settings.json`:

```json
{ "mcpServers": { "zikra": { "url": "http://localhost:8000/mcp", "headers": { "Authorization": "Bearer YOUR_TOKEN" } } } }
```

**Don't have a server yet?** → [Step 1 below](#step-1--install-the-server) takes ~2 minutes.

---

Most AI memory tools solve one problem: one agent remembers one session better.

Zikra solves a harder problem: **multiple people running multiple AI agents across multiple projects** — all sharing the same memory pool, with the right person scoped to the right project, the right agent pulling the right context, and millions of memories staying fresh through built-in hygiene scoring.

It's not session memory. It's the shared brain for an AI-native team.

| What you get | What that means |
|---|---|
| **Multi-agent** | Claude Code, Gemini CLI, Codex — one pool, one token | 
| **Multi-person** | Owner / admin / dev / viewer roles per project |
| **Multi-project** | Isolated namespaces; one team runs `veltisai`, `design`, `global` |
| **Scale** | PostgreSQL backend — handles millions of memories without index rebuilds |
| **Memory hygiene** | Built-in hygiene prompt: confidence decay, orphan detection, stale cleanup |
| **Structure** | Not just "save text" — decisions, requirements, prompts, errors, session diaries |
| **Auto-save** | Stop + PreCompact hooks write every session automatically |

— Mukarram

---

## How Zikra compares

| | **Zikra** | MCP Memory¹ | mem0 | basic-memory | MemoryMesh |
|---|---|---|---|---|---|
| Works across **multiple AI tools** | ✅ | ❌ | ✅ paid | ❌ | ❌ |
| **Team sharing** with per-user roles | ✅ RBAC | ❌ | ✅ paid | ❌ | ❌ |
| **Multi-project** namespacing | ✅ | ❌ | ✅ paid | ❌ | ❌ |
| Self-hosted, zero cloud dependency | ✅ | ✅ | ❌ | ✅ | ✅ |
| Auto-save via session hooks | ✅ | ❌ | ❌ | ❌ | ❌ |
| Hybrid vector + keyword search | ✅ | ❌ graph only | ✅ | ❌ | ❌ |
| Confidence decay / memory hygiene | ✅ built-in prompt | ❌ | ❌ | ❌ | ❌ |
| Named prompts + requirements | ✅ | ❌ | ❌ | ❌ | ❌ |
| Scales to millions of memories | ✅ Postgres | ❌ in-memory | ✅ cloud | ❌ | ❌ |
| License | MIT | MIT | Proprietary | MIT | MIT |

¹ `@modelcontextprotocol/server-memory` — the official Anthropic reference server.

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

The installer creates a `.env` file and generates your admin token. The server binds to `http://localhost:8000` by default.

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

The installer does this automatically when run locally.

### Step 3 — Connect your AI coding agent

Paste the prompt for your agent into a session. It handles both first install and updates.

**Claude Code:**
```
Fetch https://raw.githubusercontent.com/GetZikra/zikra/main/prompts/zikra-claude-code-setup.md
and follow every instruction in it.
```

This installs the **Stop hook** (auto-saves every session), **PreCompact hook**, and the live **statusline bar** showing run counts and memory stats.

---

## Updating Zikra

**Server:**
```bash
cd ~/zikra && ./update.sh
```

**Claude Code hooks** — re-run the onboarding prompt. It detects your existing install and only refreshes what changed.

---

## Profiles

| Profile | Storage | Hooks | Extra deps |
|---------|---------|-------|------------|
| Webhook (default) | SQLite ¹ | none | none |
| Auto-log | SQLite ¹ | session hooks | none |
| Full | SQLite ¹ or Postgres | hooks + daemon | asyncpg (Postgres only) |

¹ **SQLite is for local / single-user only.** For team deployments set `DB_BACKEND=postgres`.

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
| `OPENAI_API_BASE` | No | `https://api.openai.com/v1` | Swap for local or compatible embedding endpoint |
| `ZIKRA_EMBEDDING_MODEL` | No | `text-embedding-3-small` | Embedding model name |
| `ZIKRA_DECAY_DAYS` | No | `30` | Memory half-life in days |
| `ZIKRA_FREQUENCY_WEIGHT` | No | `0.1` | Access-frequency boost weight |

---

## How results are ranked

Every search result passes through scoring:

- **Age** — recent memories rank higher. Half-life: 30 days. Floor: 0.05.
- **Access frequency** — frequently used prompts surface higher (log scale).
- **Confidence** — memories saved with lower `confidence_score` rank lower.

---

## Command reference

All commands are `POST /webhook/zikra` with `Authorization: Bearer <token>`.

| Command | Aliases | Description |
|---|---|---|
| `search` | `find`, `query`, `recall` | Hybrid semantic + keyword search |
| `save_memory` | `save`, `store` | Save a memory with embedding |
| `get_memory` | `fetch_memory` | Retrieve by title or `id` |
| `get_prompt` | `fetch_prompt` | Retrieve a named prompt |
| `log_run` | `log_session` | Log a completed agent run |
| `log_error` | `log_bug` | Log an error |
| `save_requirement` | — | Save a project requirement |
| `save_prompt` | `write_prompt` | Save a prompt with embedding |
| `list_prompts` | `get_prompts` | List prompts for a project |
| `list_requirements` | `list_reqs` | List requirements |
| `promote_requirement` | `promote` | Change a requirement's type |
| `create_token` | `new_token` | Generate a bearer token (owner role) |
| `get_schema` | `schema` | DB DDL introspection |
| `zikra_help` | `help` | Full command reference |
| `debug_protocol` | — | Backend diagnostics |

**Roles:** `owner` · `admin` · `developer` · `viewer`

---

## PostgreSQL backend

```
DB_BACKEND=postgres
DB_HOST=localhost
DB_PORT=5432
DB_NAME=ai_zikra
DB_USER=postgres
DB_PASSWORD=yourpassword
```

```bash
pip install -e ".[postgres]"
```

---

## License

MIT — see [LICENSE](LICENSE)

*Design in Claude Web. Execute in Claude Code. Share with your whole team.*
*Claude Web · Claude Code · Gemini CLI · Codex · any agent that can POST.*
