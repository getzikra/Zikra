# Zikra

> Shared memory layer for AI agents and developer teams.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-316192?style=flat&logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![n8n](https://img.shields.io/badge/n8n-FF6D5A?style=flat&logo=n8n&logoColor=white)](https://n8n.io/)

Self-hosted · Agent-agnostic · PostgreSQL + pgvector · n8n

```
zikra 17 runs · 847 memories │ you@team-server │ Sonnet 4.6 │ ~/project (main) │ 387K/200K ████░░░░░░ 45%
```

---

I built Zikra because I was frustrated. I like doing architecture and research on Claude Web — it can browse sites, do deep research, give real suggestions on system design. But when it came time to actually run the code, that's Claude Code's job. The problem? They don't talk to each other. Every new session, you're starting from scratch.

So I built a shared memory layer that sits between all of them. It grew from there — more people joined, and suddenly decisions made in one session needed to be visible to everyone. Requirements written by one person needed to reach Claude Code running on a different machine. That's what this repo is.

**This is the full stack: PostgreSQL + pgvector + n8n.** If you're a solo developer, start with [Zikra Lite](https://github.com/getzikra/zikra-lite) instead — it's a single Python process that takes 60 seconds to set up.

— Mukarram

---

## What it solves

- **Session amnesia:** Claude forgets everything between sessions → Zikra remembers across all of them.
- **Context fragmentation:** Different machines have no shared context → every agent reads the same pool.
- **Team silos:** Decisions made in one session invisible to everyone else → requirements sync automatically.
- **Agent lock-in:** Claude, Gemini, ChatGPT all work in silos → Zikra is agent-agnostic, same API for all.

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
