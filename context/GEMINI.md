# Zikra for Gemini CLI

> Zikra persistent memory — Gemini CLI edition.
> All API calls use curl. Gemini CLI does not use Claude Code hooks.

Runner:          RUNNER_PLACEHOLDER
Default project: DEFAULT_PROJECT_PLACEHOLDER
Webhook:         ZIKRA_URL_PLACEHOLDER
Bearer:          ZIKRA_TOKEN_PLACEHOLDER

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

Use curl for every Zikra operation. There is no MCP integration for Zikra —
use only the curl commands below.

```bash
curl -s -X POST "ZIKRA_URL_PLACEHOLDER" \
  -H "Authorization: Bearer ZIKRA_TOKEN_PLACEHOLDER" \
  -H "Content-Type: application/json" \
  -H "User-Agent: curl/7.81.0" \
  -d '{"command":"...","project":"DEFAULT_PROJECT_PLACEHOLDER",...}'
```

---

## Session workflow for Gemini CLI

Because Gemini CLI does not have a Stop hook, you must manually log runs
and save memories. Follow this pattern at the start and end of each session:

**Start of session:**
```bash
# 1. Search for relevant context
curl -s -X POST "ZIKRA_URL_PLACEHOLDER" \
  -H "Authorization: Bearer ZIKRA_TOKEN_PLACEHOLDER" \
  -H "Content-Type: application/json" \
  -H "User-Agent: curl/7.81.0" \
  -d '{"command":"search","query":"<your topic>","project":"DEFAULT_PROJECT_PLACEHOLDER","max_results":5}'
```

**End of session:**
```bash
# 2. Log the run
curl -s -X POST "ZIKRA_URL_PLACEHOLDER" \
  -H "Authorization: Bearer ZIKRA_TOKEN_PLACEHOLDER" \
  -H "Content-Type: application/json" \
  -H "User-Agent: curl/7.81.0" \
  -d '{
    "command":               "log_run",
    "project":               "DEFAULT_PROJECT_PLACEHOLDER",
    "runner":                "RUNNER_PLACEHOLDER",
    "status":                "success",
    "output_summary":        "Summary of what was accomplished.",
    "tokens_input":          0,
    "tokens_output":         0,
    "tokens_cache_read":     0,
    "tokens_cache_creation": 0
  }'
```

---

## Projects

| Project  | Description                              |
|----------|------------------------------------------|
| veltisai | Main product                             |
| molten8  | n8n workflow engine                      |
| zikra    | This memory system                       |
| global   | Cross-project memories (shared by all)   |

Replace with your own project names.

---

## Key commands

### search

```bash
curl -s -X POST "ZIKRA_URL_PLACEHOLDER" \
  -H "Authorization: Bearer ZIKRA_TOKEN_PLACEHOLDER" \
  -H "Content-Type: application/json" \
  -H "User-Agent: curl/7.81.0" \
  -d '{
    "command":     "search",
    "query":       "database schema",
    "project":     "DEFAULT_PROJECT_PLACEHOLDER",
    "max_results": 5
  }'
```

### save_memory

```bash
curl -s -X POST "ZIKRA_URL_PLACEHOLDER" \
  -H "Authorization: Bearer ZIKRA_TOKEN_PLACEHOLDER" \
  -H "Content-Type: application/json" \
  -H "User-Agent: curl/7.81.0" \
  -d '{
    "command":     "save_memory",
    "project":     "DEFAULT_PROJECT_PLACEHOLDER",
    "memory_type": "decision",
    "title":       "title of your decision",
    "content_md":  "What was decided and why.",
    "tags":        null,
    "created_by":  "RUNNER_PLACEHOLDER"
  }'
```

### get_prompt

```bash
curl -s -X POST "ZIKRA_URL_PLACEHOLDER" \
  -H "Authorization: Bearer ZIKRA_TOKEN_PLACEHOLDER" \
  -H "Content-Type: application/json" \
  -H "User-Agent: curl/7.81.0" \
  -d '{
    "command":     "get_prompt",
    "prompt_name": "your-prompt-name",
    "project":     "DEFAULT_PROJECT_PLACEHOLDER",
    "runner":      "RUNNER_PLACEHOLDER"
  }'
```

### log_run

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
    "output_summary":        "What was built or fixed this session.",
    "tokens_input":          8000,
    "tokens_output":         2000,
    "tokens_cache_read":     0,
    "tokens_cache_creation": 0
  }'
```

### log_error

```bash
curl -s -X POST "ZIKRA_URL_PLACEHOLDER" \
  -H "Authorization: Bearer ZIKRA_TOKEN_PLACEHOLDER" \
  -H "Content-Type: application/json" \
  -H "User-Agent: curl/7.81.0" \
  -d '{
    "command":    "log_error",
    "project":    "DEFAULT_PROJECT_PLACEHOLDER",
    "title":      "error title here",
    "content_md": "Detailed description of what failed and what was tried."
  }'
```

---

## Gotchas

- **`"tags": null`** — pass `null`, not an array, when `content_md` contains
  curly braces `{}`. Mixed arrays + `{}` content breaks n8n JSON parsing.

- **User-Agent required** — always include `User-Agent: curl/7.81.0`.

- **No hooks** — Gemini CLI has no Stop/PreCompact equivalent. You must
  manually call `log_run` at end of session and `save_memory` after decisions.

- **Gemini token counts** — Gemini uses `input_token_count` /
  `output_token_count` in its API response metadata. Map these to
  `tokens_input` / `tokens_output` when logging runs.
