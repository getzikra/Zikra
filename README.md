# Zikra 🚀

> Enterprise-grade AI persistent memory and project management for developer teams.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-316192?style=flat&logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![n8n](https://img.shields.io/badge/n8n-FF6D5A?style=flat&logo=n8n&logoColor=white)](https://n8n.io/)

Self-hosted · Agent-agnostic · PostgreSQL + pgvector · n8n

```
zikra 17 runs · 847 memories │ you@team-server │ Sonnet 4.6 │ ~/project (main) │ 387K/200K ████░░░░░░ 45%
```

Zikra gives every AI agent on every machine a shared long-term memory — decisions, errors, schemas, and prompts — searchable, persistent, and synced across your entire organization.

## What it solves

- **The Amnesia Problem:** Claude forgets everything between sessions → Zikra remembers forever.
- **The Fragmentation Problem:** Different machines have no shared context → Zikra syncs across all of them via our robust n8n backend.
- **The Silo Problem:** Gemini, Codex, Claude all work in silos → Zikra is agent-agnostic.
- **The Team Barrier:** Teams have no shared AI memory → Zikra has multi-user token access and RBAC.

## Solo Developer?
If you just want a single-player version that runs on your laptop with no dependencies, check out **[Zikra-Lite](https://github.com/YOUR_GITHUB_USERNAME/Zikra-Lite)** (Python + SQLite).

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

## License

MIT — see [LICENSE](LICENSE)
