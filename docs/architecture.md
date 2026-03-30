# Zikra Architecture

## Overview

Zikra is a lightweight persistent memory layer for AI agents. It has four
components that work together to give every agent session access to a shared,
searchable memory store.

```
┌─────────────────────────────────────────────────────────────────────┐
│                        AGENT MACHINES                                │
│                                                                      │
│  ┌─────────────┐   ┌─────────────┐   ┌─────────────┐               │
│  │ Claude Code │   │ Gemini CLI  │   │  Any agent  │               │
│  │ (machine A) │   │ (machine B) │   │ (machine C) │               │
│  └──────┬──────┘   └──────┬──────┘   └──────┬──────┘               │
│         │                 │                  │                       │
│    hooks + curl      manual curl          curl                       │
│         │                 │                  │                       │
└─────────┼─────────────────┼──────────────────┼─────────────────────┘
          │                 │                  │
          └─────────────────┴──────────────────┘
                            │
                    HTTPS POST /webhook/zikra
                            │
┌───────────────────────────▼─────────────────────────────────────────┐
│                         ZIKRA SERVER                                  │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │                      n8n Workflow                            │   │
│  │                                                              │   │
│  │  webhook trigger → auth check → route by command            │   │
│  │       ↓                                                      │   │
│  │  search → embed query → pgvector cosine search + FTS        │   │
│  │  save   → embed content → INSERT/UPSERT memories            │   │
│  │  log    → INSERT active_runs                                 │   │
│  │  prompt → SELECT memories WHERE memory_type='prompt'        │   │
│  └──────────────────────────────┬───────────────────────────────┘   │
│                                 │                                    │
│  ┌──────────────────────────────▼───────────────────────────────┐   │
│  │                   PostgreSQL + pgvector                       │   │
│  │                                                              │   │
│  │   zikra.memories        zikra.active_runs                    │   │
│  │   zikra.access_tokens   zikra.prompt_runs                   │   │
│  │   zikra.token_projects  zikra.migrations                    │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Memory flow

```
1. Agent starts a session
        │
        ▼
2. Agent calls: search {query, project}
        │
        ▼
3. n8n embeds the query via OpenAI API
        │
        ▼
4. pgvector cosine similarity search + full-text search
   → top-N memories returned ranked by score
        │
        ▼
5. Agent reads context, begins work
        │
        ▼
6. Agent makes a decision
        │
        ▼
7. Agent calls: save_memory {title, content_md, memory_type=decision}
        │
        ▼
8. n8n embeds content → INSERT into zikra.memories
        │
        ▼
9. Session ends (Claude Code fires Stop hook automatically)
        │
        ▼
10. zikra_autolog.sh generates diary via claude -p
        │
        ▼
11. log_run POSTed to Zikra → stored in zikra.active_runs
        │
        ▼
12. Next session on any machine finds this memory via search
```

---

## Install profiles

### Minimal (--minimal)

What it adds:
- `~/.claude/zikra_autolog.sh` — hook script
- `~/.claude/CLAUDE.md` — agent context file
- Stop hook wired in `~/.claude/settings.json`

What this gives you:
- Automatic diary saving at session end
- Manual search/save via curl
- No real-time token tracking

### Standard (--standard) — recommended

Everything in Minimal, plus:
- PreCompact hook wired with matcher `auto`

What this gives you:
- Diary saved before context compaction (prevents memory loss)
- Summary captured from the last 100 transcript lines before compaction

### Full (--full)

Everything in Standard, plus:
- `~/.claude/zikra_watcher.py` — session capture daemon
- `~/.claude/hooks/zikra-statusline.js` — live statusline
- `~/.claude/cache/zikra-stats.json` — local stats cache
- `statusLine` wired in settings.json
- systemd user service on Linux (auto-starts watcher on login)

What this gives you:
- Real-time session capture without relying solely on hooks
- Token usage tracked per session
- Live statusline showing runs, memory count, context usage
- Short/ad-hoc sessions captured (stable 2s, age < 30s threshold)

---

## Retention and decay

Zikra uses a confidence score (0.0–1.0) combined with a weekly cron job
to decay and archive old memories.

### Confidence decay half-lives by type

| Memory type   | Half-life | Notes                                      |
|---------------|-----------|--------------------------------------------|
| conversation  | 30 days   | Diary entries — fade after a month         |
| error         | 60 days   | Bugs stay relevant longer                  |
| decision      | 180 days  | Architectural decisions stay for 6 months  |
| schema        | 365 days  | Schema docs rarely go stale quickly        |
| prompt        | none      | Prompts never decay (confidence=1.0)       |

### Weekly cron behavior

The n8n workflow includes a weekly schedule trigger that:
1. Selects memories with `confidence > 0` and `status = 'active'`
2. Applies the type-specific half-life formula
3. Memories below `confidence < 0.1` are moved to `status = 'archived'`
4. Archived memories are still searchable but ranked lower

---

## Multi-machine design

One Zikra server serves all machines. Each machine:
- Has its own copy of `~/.claude/zikra_autolog.sh` (patched with shared credentials)
- Uses the same webhook URL and bearer token
- Tags memories with `created_by: <hostname>`

Search results are not filtered by machine — they return memories from all
runners across all machines for the given project. This is the entire point:
a decision made on machine A is immediately findable from machine B.

---

## Multi-agent design

Any agent that can run curl can use Zikra. The webhook interface is identical
regardless of which AI model is calling it.

| Agent       | How it calls Zikra               | Auto-logging         |
|-------------|----------------------------------|----------------------|
| Claude Code | curl from hooks + CLAUDE.md      | Stop + PreCompact    |
| Gemini CLI  | curl from GEMINI.md instructions | Manual               |
| OpenAI      | curl from system prompt          | Manual               |
| Custom      | curl or HTTP client              | Custom hook          |

All agents share the same PostgreSQL tables. A decision saved by Gemini on one
machine is found by Claude on another.

---

## Security model

### Bearer tokens

Every request must include `Authorization: Bearer <token>`. The n8n workflow
validates the token against `zikra.access_tokens` before processing any command.

Tokens have three roles:
- `reader` — may call: search, get_memory, get_prompt, list_requirements
- `writer` — may call all reader commands plus: save_memory, log_run, log_error, save_requirement
- `admin` — may call all commands plus: create_token, promote_requirement

### Project scoping

If a token has rows in `zikra.token_projects`, it can only access those
specific projects. If no rows exist, the token can access all projects.

This allows team setups where:
- Shared team token has no project restrictions (all projects)
- Per-project tokens are scoped to one project each
- CI/CD tokens are scoped to a single project

### Transport security

Zikra is designed to run behind a reverse proxy (nginx, Caddy, Cloudflare Tunnel)
with HTTPS termination. The docker-compose setup exposes n8n on port 5678 locally;
configure TLS at the proxy layer before exposing to the internet.
