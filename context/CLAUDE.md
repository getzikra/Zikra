# Zikra — AI Persistent Memory

Runner:          RUNNER_PLACEHOLDER
Default project: DEFAULT_PROJECT_PLACEHOLDER
Webhook:         ZIKRA_URL_PLACEHOLDER
Bearer:          ZIKRA_TOKEN_PLACEHOLDER

> IMPORTANT: NEVER use n8n MCP tools to call Zikra. Use curl only.
> availableInMCP is false for all Zikra tools.

---

## Identity

| Field           | Value                                           |
|-----------------|-------------------------------------------------|
| Runner          | RUNNER_PLACEHOLDER                              |
| Default project | DEFAULT_PROJECT_PLACEHOLDER                     |
| Webhook URL     | ZIKRA_URL_PLACEHOLDER                           |
| Auth header     | Authorization: Bearer ZIKRA_TOKEN_PLACEHOLDER   |
| User-Agent      | curl/7.81.0  ← always include                  |

---

## How to call Zikra

Use curl for every Zikra operation. The n8n MCP server is for other workflows,
not Zikra — using it for Zikra calls will silently fail.

```bash
curl -s -X POST "ZIKRA_URL_PLACEHOLDER" \
  -H "Authorization: Bearer ZIKRA_TOKEN_PLACEHOLDER" \
  -H "Content-Type: application/json" \
  -H "User-Agent: curl/7.81.0" \
  -d '{"command":"...","project":"DEFAULT_PROJECT_PLACEHOLDER",...}'
```

---

## Projects

| Project  | Description                              |
|----------|------------------------------------------|
| veltisai | Main product                             |
| molten8  | n8n workflow engine                      |
| zikra    | This memory system                       |
| global   | Cross-project memories (shared by all)   |

Replace the above with your own project names after install.

---

## Key commands

### search — find relevant memories before starting work

```bash
curl -s -X POST "ZIKRA_URL_PLACEHOLDER" \
  -H "Authorization: Bearer ZIKRA_TOKEN_PLACEHOLDER" \
  -H "Content-Type: application/json" \
  -H "User-Agent: curl/7.81.0" \
  -d '{
    "command":     "search",
    "query":       "database schema migration",
    "project":     "DEFAULT_PROJECT_PLACEHOLDER",
    "max_results": 5
  }'
```

### save_memory — record a decision immediately after making it

```bash
curl -s -X POST "ZIKRA_URL_PLACEHOLDER" \
  -H "Authorization: Bearer ZIKRA_TOKEN_PLACEHOLDER" \
  -H "Content-Type: application/json" \
  -H "User-Agent: curl/7.81.0" \
  -d '{
    "command":     "save_memory",
    "project":     "DEFAULT_PROJECT_PLACEHOLDER",
    "memory_type": "decision",
    "title":       "chose postgres over sqlite for vector search",
    "content_md":  "PostgreSQL selected because we need pgvector for semantic search. SQLite has no stable vector extension.",
    "tags":        null,
    "created_by":  "RUNNER_PLACEHOLDER"
  }'
```

### get_prompt — fetch a stored reusable prompt

```bash
curl -s -X POST "ZIKRA_URL_PLACEHOLDER" \
  -H "Authorization: Bearer ZIKRA_TOKEN_PLACEHOLDER" \
  -H "Content-Type: application/json" \
  -H "User-Agent: curl/7.81.0" \
  -d '{
    "command":     "get_prompt",
    "prompt_name": "code-review",
    "project":     "DEFAULT_PROJECT_PLACEHOLDER",
    "runner":      "RUNNER_PLACEHOLDER"
  }'
```

### log_run — record what this session accomplished

```bash
curl -s -X POST "ZIKRA_URL_PLACEHOLDER" \
  -H "Authorization: Bearer ZIKRA_TOKEN_PLACEHOLDER" \
  -H "Content-Type: application/json" \
  -H "User-Agent: curl/7.81.0" \
  -d '{
    "command":               "log_run",
    "project":               "DEFAULT_PROJECT_PLACEHOLDER",
    "runner":                "RUNNER_PLACEHOLDER",
    "status":                "success",
    "output_summary":        "Built the auth module. Added JWT validation and refresh token rotation.",
    "tokens_input":          12000,
    "tokens_output":         3200,
    "tokens_cache_read":     0,
    "tokens_cache_creation": 0
  }'
```

### log_error — track a bug or failure

```bash
curl -s -X POST "ZIKRA_URL_PLACEHOLDER" \
  -H "Authorization: Bearer ZIKRA_TOKEN_PLACEHOLDER" \
  -H "Content-Type: application/json" \
  -H "User-Agent: curl/7.81.0" \
  -d '{
    "command":    "log_error",
    "project":    "DEFAULT_PROJECT_PLACEHOLDER",
    "title":      "prod migration failed — column not nullable",
    "content_md": "Column users.role was NOT NULL but INSERT did not provide a value. Fixed by adding DEFAULT 'viewer' to the column definition."
  }'
```

---

## Running prompts — full workflow

```bash
# 1. Fetch the prompt and capture the run ID
PROMPT_RESP=$(curl -s -X POST "ZIKRA_URL_PLACEHOLDER" \
  -H "Authorization: Bearer ZIKRA_TOKEN_PLACEHOLDER" \
  -H "Content-Type: application/json" \
  -H "User-Agent: curl/7.81.0" \
  -d '{
    "command":     "get_prompt",
    "prompt_name": "YOUR_PROMPT_NAME",
    "project":     "DEFAULT_PROJECT_PLACEHOLDER",
    "runner":      "RUNNER_PLACEHOLDER"
  }')

# 2. Store the run ID so the watcher can link this log_run to the prompt
PROMPT_RUN_ID=$(echo "$PROMPT_RESP" | python3 -c \
  "import json,sys; print(json.load(sys.stdin).get('run_id',''))")
echo "$PROMPT_RUN_ID" > /tmp/zikra_prompt_id

# 3. Read the prompt content
CONTENT=$(echo "$PROMPT_RESP" | python3 -c \
  "import json,sys; print(json.load(sys.stdin).get('content_md',''))")

# 4. Execute the prompt (Claude acts on $CONTENT)
# 5. log_run fires automatically via Stop hook — linked via /tmp/zikra_prompt_id
```

---

## Gotchas

- **`"tags": null`** — always pass `null` (not an array) when `content_md`
  contains curly braces `{}`. Passing an array alongside `{}` in the body
  triggers a JSON parse error inside n8n.

- **User-Agent required** — always include `User-Agent: curl/7.81.0`.
  Some n8n configurations reject requests without a recognized User-Agent.

- **availableInMCP: false** — the Zikra MCP tools are disabled by design.
  Do not attempt to call them via MCP. Use curl only.

- **Dollar signs in PostgreSQL** — when writing `$1`, `$2` style parameters
  inside bash heredocs, escape as `\$1` to prevent shell expansion.

- **Duplicate diary sentinel** — the Stop hook writes `/tmp/zikra_last_diary`
  to avoid saving two diary entries if Claude Code fires Stop twice quickly.
  This file is safe to delete if you need to force a re-save.
