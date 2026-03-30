# zikra

> AI persistent memory and project management for developer teams.

Self-hosted · Agent-agnostic · PostgreSQL + pgvector · n8n

```
zikra 17 runs · 847 memories │ you@yourserver │ Sonnet 4.6 │ ~/project (main) │ 387K/200K ████░░░░░░ 45%
```

Zikra gives every AI agent on every machine a shared long-term memory —
decisions, errors, schemas, and prompts — searchable, persistent, cross-machine.

## What it solves

- Claude forgets everything between sessions → Zikra remembers forever
- Different machines have no shared context → Zikra syncs across all of them
- Gemini, Codex, Claude all work in silos → Zikra is agent-agnostic
- Teams have no shared AI memory → Zikra has multi-user token access

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

- PostgreSQL with pgvector extension
- n8n (self-hosted)
- curl and python3 on every machine
- node (for --full statusline only)

## Documentation

- [Architecture](docs/architecture.md)
- [Install guide](docs/install.md)
- [Commands reference](docs/commands.md)

## License

MIT — see [LICENSE](LICENSE)
