# Zikra

> Persistent memory for Claude Code, Cursor, Gemini CLI, and other AI coding agents — shared across sessions and machines.

Zikra Full is for teams. If you are a solo developer, start with [Zikra Lite](https://github.com/getzikra/zikra-lite) — 3-step install, no Docker, no PostgreSQL.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-316192?style=flat&logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![n8n](https://img.shields.io/badge/n8n-FF6D5A?style=flat&logo=n8n&logoColor=white)](https://n8n.io/)
[![MCP](https://img.shields.io/badge/MCP-native-blue)](https://modelcontextprotocol.io/)

**Website:** [zikra.dev](https://zikra.dev) · Self-hosted · Agent-agnostic · MCP native · PostgreSQL + pgvector · n8n

```
zikra 17 runs · 847 memories │ you@team-server │ Sonnet 4.6 │ ~/project (main) │ 387K/200K ████░░░░░░ 45%
```

---

AI agents have no memory between sessions. Claude Code forgets your architecture decisions overnight. Gemini CLI has no idea what Claude Web researched this morning. Cursor on your teammate's machine has never seen your decisions.

Zikra fixes that. It's a **MCP-native memory server** that all your agents connect to. Every decision, requirement, error, and session summary — saved, searchable, and shared across every tool and every machine.

I built it because I was doing architecture on Claude Web and running code on Claude Code — two tools with no shared context. It grew from a single file into this when teammates joined and decisions needed to be visible everywhere.

**This is the full stack: PostgreSQL + pgvector + n8n.** For solo developers, start with [Zikra Lite](https://github.com/getzikra/zikra-lite) — single Python process, 60-second setup, same API.

— Mukarram

---

## What it solves

- **Session amnesia:** Claude Code forgets everything between sessions → Zikra remembers across all of them.
- **Context fragmentation:** Different machines, different agents, no shared context → every agent reads the same pool.
- **Team silos:** Decisions made in one session invisible to everyone else → requirements sync automatically.
- **Agent lock-in:** Claude, Gemini, ChatGPT, Cursor all work in silos → Zikra is agent-agnostic, same API for all.
- **MCP integration:** Connects to Claude Desktop and any MCP-compatible client natively.

## MCP Setup (Claude Desktop)

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "zikra": {
      "url": "https://your-zikra-server/mcp",
      "headers": { "Authorization": "Bearer YOUR_ZIKRA_TOKEN" }
    }
  }
}
```

## Install

1. Clone the repo
2. Copy `.env.example` to `.env` and fill in credentials
3. `docker compose up -d`
4. Import `workflow/zikra_mcp_router.json` into n8n and activate it
   - After importing, open the `SM Embed`, `SR Embed`, and `LE Embed` HTTP Request nodes and replace `YOUR_LITELLM_MASTER_KEY_HERE` in the Authorization header with the value of `LITELLM_MASTER_KEY` from your `.env`
5. Run the Claude Code onboarding command (see below)

**Onboard Claude Code (after install):**
```
Fetch https://raw.githubusercontent.com/getzikra/zikra/main/prompts/g_zikra.md
and follow every instruction in it.
```
Paste into any Claude Code session. Installs hooks and statusline bar automatically.

## Web UI

Coming soon. A web interface for browsing memories, viewing prompt runs, managing tokens, and searching across your project is planned for a future release.

## What each profile installs

|                                              | Minimal | Standard | Full |
|----------------------------------------------|---------|----------|------|
| Stop hook — auto session logging             | ✅      | ✅       | ✅   |
| PreCompact hook — save before context loss   | ❌      | ✅       | ✅   |
| Diary auto-extract on session end            | ❌      | ✅       | ✅   |
| Session capture daemon                       | ❌      | ❌       | ✅   |
| Statusline bar in Claude Code                | ❌      | ❌       | ✅   |

<!-- Shared file — keep in sync with zikra-lite/hooks/ when editing -->

## How results are ranked

Zikra does not return results in raw similarity order. Every search result
passes through a scoring step that adjusts ranking based on:

- **Age** — recent memories rank higher. A memory created today scores
  roughly 2× higher than the same memory from 30 days ago, and 10× higher
  than one from 90 days ago. Memories never disappear — they decay to a
  floor of 5% weight and stay searchable.
- **Access frequency** — for prompts, every run increments a counter.
  Frequently used prompts surface higher in search results.
- **Confidence** — memories saved with a lower confidence_score rank lower.
  Use confidence to signal uncertainty when saving memories.

No configuration required. This works automatically on every search.

## Requirements

- [Docker](https://docs.docker.com/get-docker/) + [Docker Compose](https://docs.docker.com/compose/install/) (v2+) — required for the recommended install
- PostgreSQL with `pgvector` extension
- n8n (self-hosted or cloud)
- curl and python3 on every machine
- node (for `--full` statusline only)
- **OpenAI API key** — required for semantic embeddings. The `sys_litellm` service in `docker-compose.yml` proxies embedding calls to OpenAI using `OPENAI_API_KEY` from your `.env` file. After importing the n8n workflow, update the `LITELLM_MASTER_KEY` in your `.env` and set the same value in the Authorization header of the `SM Embed`, `SR Embed`, and `LE Embed` HTTP Request nodes inside the workflow.

## Documentation

- [Architecture](docs/architecture.md)
- [Install guide](docs/install.md)
- [Commands reference](docs/commands.md)
- [Onboarding guide](docs/onboarding.md)

## Zikra Lite vs Zikra

| Feature | Lite (SQLite) | Zikra (Postgres + n8n) |
|---------|--------------|------------------------|
| Concurrent writes | Limited | Unlimited |
| Vector search | sqlite-vec | pgvector |
| Scale | Millions of rows | Billions of rows |
| n8n workflows | ❌ | ✅ Visual editor, scheduling |
| Smart ranking | Age + frequency + confidence | Age + frequency + confidence |
| Admin UI | Basic (built-in) | n8n dashboard + direct DB |
| Backup | Copy one file | pg_dump, managed |
| Setup time | 60 seconds | 30–60 minutes |

Same API. Same commands. Same JSON shapes. Migration from Lite to Full requires an export/import step — schema differences exist (SQLite vs PostgreSQL, `person_name` vs `label` in the tokens table). See [docs/migrate.md](docs/migrate.md) or [GitHub issues](https://github.com/getzikra/zikra/issues) for a migration guide.

## Accessing Zikra from anywhere

Zikra Full runs on your server and is already accessible
to your whole team at the webhook URL in your `.env` file.

For remote access without a public server, see
[Zikra Lite + Cloudflare Tunnel](https://github.com/getzikra/zikra-lite#sharing-zikra-with-your-team) in the zikra-lite repo.

## License

MIT — see [LICENSE](LICENSE)
