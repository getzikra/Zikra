# Zikra — Onboarding Guide

## Memory types

| Type | What it is | Example |
|------|-----------|---------|
| `decision` | Choices made and why | "Chose JWT over sessions — stateless fits our multi-region setup" |
| `architecture` | System design, schema, structure | "Auth service owns all token issuance. No other service mints tokens." |
| `requirement` | Features and specs | "Users must be able to export their data as CSV within 2 clicks" |
| `prompt` | Saved Claude Code prompts | "zikra:rebuild_auth — runbook for replacing auth middleware" |
| `conversation` | Session summaries, diary entries, auto-captured context | Auto-logged by the Stop hook at session end |
| `error` | Bugs and fixes | "SQLite lock on concurrent writes — fixed by WAL mode" |

---

## User roles

> The role matrix below is enforced by Zikra. `create_token` requires `owner` or `admin` role.

| Role | Search | Save memories | Save prompts | Create tokens | Delete |
|------|--------|--------------|-------------|--------------|--------|
| owner | yes | yes | yes | yes | yes |
| admin | yes | yes | yes | yes | no |
| developer | yes | yes | no | no | no |
| requirements_engineer | yes | requirements only | no | no | no |
| viewer | yes | no | no | no | no |

---

## Personas

Tokens have an optional `persona` string that shapes how the agent approaches its work:

| Persona | Focus |
|---------|-------|
| `architect` | System design, trade-offs, structure |
| `developer` | Code, implementation, bugs |
| `requirements_engineer` | Capturing and validating requirements |
| Any custom string | Whatever you define |

Set a persona when creating a token in the Web UI or via `create_token`.

---

## Onboarding: Web UI

1. Open https://zikra.yourdomain.com (or your self-hosted URL)
2. Enter your token (issued by your admin via the Tokens tab)
3. Select your default project (e.g. `global`)
4. Browse memories, search, view runs, manage tokens
5. Copy the MCP config from Settings and paste it into Claude Desktop

---

## Onboarding: Claude Code

Paste this into Claude Code to install Zikra automatically:

```
Fetch https://raw.githubusercontent.com/getzikra/zikra/main/prompts/g_zikra.md
and follow every instruction in it.
URL: https://n8n.yourdomain.com/webhook/zikra, Token: from your admin, Project: global
```

The installer wires up the Stop hook, PreCompact hook, CLAUDE.md context injection, and statusline. After that, memory is automatic — every session is logged without you thinking about it.

---

## Adding a teammate

1. Open the Web UI → Tokens tab → Create token
2. Enter name, label, role, and default project
3. Share the token with your teammate
4. They paste the Claude Code install prompt above and enter the token when prompted

Zikra runs on your server — teammates connect directly to your webhook URL. No tunnel needed.

---

## Projects

A project is a namespace like `global`, `backend`, or `mobile`.

- Use `global` for team-wide memories that everyone should see
- Use project names for scoped work — only developers on that project need to search it
- A token's `default_project` controls where memories land when no project is specified
- You can search across all projects by passing `"project": null` or omitting it

---

## How the hooks work

| Hook | When it fires | What it does |
|------|--------------|-------------|
| Stop | Every time a Claude Code session ends | Logs a diary entry to Zikra automatically |
| PreCompact | Before context window reset | Saves a summary of the current context |

Both hooks are silent — they run in the background and never interrupt your work.
