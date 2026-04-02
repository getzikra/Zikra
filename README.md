# Zikra

> Persistent memory for Claude Code, Cursor, Gemini CLI, and other AI coding agents — shared across sessions and machines.

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

```bash
curl -fsSL https://zikra.dev/install.sh | bash
```

Choose a profile:

```bash
# Minimal — hooks + context file only (60 seconds)
curl -fsSL https://zikra.dev/install.sh | bash -s -- --minimal

# Standard — adds diary auto-extract + PreCompact hook (recommended)
curl -fsSL https://zikra.dev/install.sh | bash -s -- --standard

# Full — adds statusline bar + session capture daemon
curl -fsSL https://zikra.dev/install.sh | bash -s -- --full
```

## Web UI

Zikra includes a web interface to browse memories, view prompt runs, manage tokens, and search across your project.

To start the UI:

```bash
cd ui
npm install
npm run dev
```

Open http://localhost:5173 in your browser.

The UI reads your token and webhook URL from `ui/.env` — copy `ui/.env.example` and fill in your values, pointing `VITE_ZIKRA_URL` to your n8n webhook URL.

## What each profile installs

|                                              | Minimal | Standard | Full |
|----------------------------------------------|---------|----------|------|
| Stop hook — auto session logging             | ✅      | ✅       | ✅   |
| PreCompact hook — save before context loss   | ❌      | ✅       | ✅   |
| Diary auto-extract on session end            | ❌      | ✅       | ✅   |
| Session capture daemon                       | ❌      | ❌       | ✅   |
| Statusline bar in Claude Code                | ❌      | ❌       | ✅   |

## Requirements

- PostgreSQL with `pgvector` extension
- n8n (self-hosted or cloud)
- curl and python3 on every machine
- node (for `--full` statusline only)

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
| Decay scoring | Manual | Automated via n8n schedule |
| Admin UI | Basic | Django admin |
| Backup | Copy one file | pg_dump, managed |
| Setup time | 60 seconds | 30–60 minutes |

Same API. Same commands. Same JSON shapes. Upgrade is just changing a URL.

## Accessing Zikra from anywhere

Zikra Full runs on your server and is already accessible
to your whole team at the webhook URL in your `.env` file.

For remote access without a public server, see
[Zikra Lite + Cloudflare Tunnel](https://github.com/getzikra/zikra-lite#sharing-zikra-with-your-team) in the zikra-lite repo.

## License

MIT — see [LICENSE](LICENSE)
