# Zikra Agent Instructions

You have access to Zikra persistent memory. Use it every session.

## Setup

Your Zikra configuration is in `~/.claude/CLAUDE.md` (Claude Code) or
`~/.gemini/GEMINI.md` (Gemini CLI). Read it at session start for your webhook
URL, bearer token, and default project.

## Session start — always do this first

```bash
curl -s -X POST "$ZIKRA_URL" \
  -H "Authorization: Bearer $ZIKRA_TOKEN" \
  -H "Content-Type: application/json" \
  -H "User-Agent: curl/7.81.0" \
  -d '{"command":"search","query":"recent decisions errors active work","project":"$DEFAULT_PROJECT","max_results":5}'
```

Read the results before doing anything else.

## Rules

1. **Search first** — always search Zikra at session start before doing any work
2. **Save immediately** — record decisions right after making them, not at the end
3. **Log errors** — when you encounter a bug or failure, log it to Zikra before fixing
4. **curl only** — never use n8n MCP tools for Zikra; use curl only
5. **null tags** — always pass `"tags": null` when `content_md` contains `{}`
6. **User-Agent** — always include `User-Agent: curl/7.81.0` in every call

## Available commands

| Command            | Purpose                                      |
|--------------------|----------------------------------------------|
| `search`           | Hybrid semantic + keyword search             |
| `save_memory`      | Store any knowledge, decision, or context    |
| `get_memory`       | Fetch a specific memory by title or ID       |
| `get_prompt`       | Load a stored reusable prompt                |
| `log_run`          | Record what this session accomplished        |
| `log_error`        | Track a bug or failure                       |
| `save_requirement` | Store a project requirement                  |
| `list_requirements`| List open requirements for a project         |
| `promote_requirement` | Promote a requirement to a decision       |
| `create_token`     | Generate a new access token                  |
| `get_schema`       | Return the database schema                   |

## Command reference

```
search:
  {"command":"search","query":"<topic>","project":"<p>","max_results":5}

save_memory:
  {"command":"save_memory","project":"<p>","memory_type":"decision",
   "title":"<t>","content_md":"...","tags":null,"created_by":"<hostname>"}

log_error:
  {"command":"log_error","project":"<p>","title":"<t>","content_md":"<detail>"}

get_prompt:
  {"command":"get_prompt","prompt_name":"<n>","project":"<p>","runner":"<hostname>"}

log_run:
  {"command":"log_run","project":"<p>","runner":"<hostname>","status":"success",
   "output_summary":"<2 sentences>","tokens_input":<n>,"tokens_output":<n>,
   "tokens_cache_read":<n>,"tokens_cache_creation":<n>}
```

## Memory types

| Type           | When to use                                     |
|----------------|-------------------------------------------------|
| `decision`     | Architecture choices, tech selections, trade-offs |
| `conversation` | Session diaries, what was worked on             |
| `error`        | Bugs encountered, how they were fixed           |
| `prompt`       | Reusable prompt templates                       |
| `requirement`  | Project requirements, acceptance criteria       |
| `context`      | Background knowledge, team conventions          |
| `schema`       | Database schemas, API contracts                 |
