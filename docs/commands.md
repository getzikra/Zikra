# Zikra Webhook Commands Reference

All commands are sent as HTTP POST to your Zikra webhook URL.

**Base request shape:**
```bash
curl -s -X POST "$ZIKRA_URL" \
  -H "Authorization: Bearer $ZIKRA_TOKEN" \
  -H "Content-Type: application/json" \
  -H "User-Agent: curl/7.81.0" \
  -d '{ "command": "<command_name>", ... }'
```

**Required on every request:**
- `Authorization: Bearer <token>` — your bearer token
- `User-Agent: curl/7.81.0` — required by some n8n configurations
- `"command"` field in the JSON body

---

## search

Search memories using semantic (vector) search combined with full-text search.
Results are ranked by a combined score. Use this at the start of every session.

**Required fields:**
- `command` — `"search"`
- `query` — string, the search query
- `project` — string, project namespace

**Optional fields:**
- `limit` — integer (default: 10, max: 100)
- `memory_type` — filter to a specific type (`"decision"`, `"error"`, etc.)
- `include_archived` — boolean (default: false)

**Example:**
```bash
curl -s -X POST "https://n8n.example.com/webhook/zikra" \
  -H "Authorization: Bearer velt-abc123" \
  -H "Content-Type: application/json" \
  -H "User-Agent: curl/7.81.0" \
  -d '{
    "command": "search",
    "query":   "authentication JWT refresh token",
    "project": "myproject",
    "limit":   5
  }'
```

**Response:**
```json
{
  "results": [
    {
      "id":          "uuid",
      "title":       "chose JWT with 15min expiry and refresh rotation",
      "memory_type": "decision",
      "content_md":  "...",
      "score":       0.912,
      "created_at":  "2026-01-15T10:30:00Z"
    }
  ],
  "count": 1
}
```

---

## save_memory

Save a new memory or update an existing one with the same title+memory_type.
Existing memories are updated (content replaced, version incremented).

**Required fields:**
- `command` — `"save_memory"`
- `project` — string
- `memory_type` — `"decision"` | `"conversation"` | `"error"` | `"schema"` | `"prompt"` | `"requirement"` | `"context"`
- `title` — string, must be unique per (title, memory_type)
- `content_md` — string, the memory content (markdown supported)
- `tags` — array of strings OR `null` — **use `null` if content_md contains `{}`**
- `created_by` — string, hostname or agent identifier

**Optional fields:**
- `module` — string, sub-module or feature area
- `source_file` — string, path to the source file this relates to
- `confidence` — float 0.0–1.0 (default: 1.0)

**Example:**
```bash
curl -s -X POST "https://n8n.example.com/webhook/zikra" \
  -H "Authorization: Bearer velt-abc123" \
  -H "Content-Type: application/json" \
  -H "User-Agent: curl/7.81.0" \
  -d '{
    "command":     "save_memory",
    "project":     "myproject",
    "memory_type": "decision",
    "title":       "use pgvector for semantic search instead of elasticsearch",
    "content_md":  "Chose pgvector because it collocates with existing Postgres, eliminating a separate service. ES would require 4GB+ RAM. Semantic search quality is comparable for our use case.",
    "tags":        ["database", "search", "architecture"],
    "created_by":  "dev-machine-01"
  }'
```

**Response:**
```json
{
  "id":      "3f2a1b4c-...",
  "status":  "saved",
  "action":  "inserted"
}
```

---

## get_prompt

Fetch a stored prompt by name. Increments access_count.

**Required fields:**
- `command` — `"get_prompt"`
- `prompt_name` — string, the title of the memory with memory_type=`"prompt"`
- `project` — string

**Example:**
```bash
curl -s -X POST "https://n8n.example.com/webhook/zikra" \
  -H "Authorization: Bearer velt-abc123" \
  -H "Content-Type: application/json" \
  -H "User-Agent: curl/7.81.0" \
  -d '{
    "command":     "get_prompt",
    "prompt_name": "weekly-code-review",
    "project":     "myproject"
  }'
```

**Response:**
```json
{
  "id":           "9a3b2c1d-...",
  "title":        "weekly-code-review",
  "content_md":   "Review the diff from the past week. Focus on: ...",
  "project":      "myproject",
  "created_at":   "2026-01-10T08:00:00Z",
  "access_count": 5
}
```

---

## log_run

Record what an agent session accomplished, including token usage.
Called automatically by the Stop hook and zikra_watcher.py daemon.

**Required fields:**
- `command` — `"log_run"`
- `project` — string
- `runner` — string, hostname
- `status` — `"success"` | `"failed"` | `"interrupted"`
- `output_summary` — string, 1–3 sentence description of what was done
- `tokens_input` — integer
- `tokens_output` — integer

**Optional fields:**
- `prompt_name` — string, name of the prompt that was run
- `cost_usd` — float, cost of the run in USD

**Example:**
```bash
curl -s -X POST "https://n8n.example.com/webhook/zikra" \
  -H "Authorization: Bearer velt-abc123" \
  -H "Content-Type: application/json" \
  -H "User-Agent: curl/7.81.0" \
  -d '{
    "command":        "log_run",
    "project":        "myproject",
    "runner":         "dev-machine-01",
    "status":         "success",
    "output_summary": "Implemented user authentication with JWT. Added refresh token rotation and blacklist. All tests passing.",
    "tokens_input":   48200,
    "tokens_output":  12400
  }'
```

**Response:**
```json
{
  "id":     "7c4d9e2f-...",
  "status": "logged"
}
```

---

## log_error

Record a bug, failure, or blocker. Stored as memory_type=`"error"` for
tracking and future search.

**Required fields:**
- `command` — `"log_error"`
- `project` — string
- `message` — string, short description of the error

**Optional fields:**
- `context_md` — string, full details: what happened, what was tried, resolution if known
- `runner` — string, hostname
- `error_type` — string, category of error
- `stack_trace` — string, stack trace if applicable

**Example:**
```bash
curl -s -X POST "https://n8n.example.com/webhook/zikra" \
  -H "Authorization: Bearer velt-abc123" \
  -H "Content-Type: application/json" \
  -H "User-Agent: curl/7.81.0" \
  -d '{
    "command":    "log_error",
    "project":    "myproject",
    "message":    "prod deploy failed — missing DATABASE_URL env var",
    "context_md": "Deploy to production failed because DATABASE_URL was not set in the environment. The .env file was not copied to the server. Fixed by adding DATABASE_URL to the deployment secrets in CI."
  }'
```

**Response:**
```json
{
  "id":     "2e8f1a3b-...",
  "status": "logged"
}
```

---

## get_memory

Fetch a specific memory by its UUID.

**Required fields:**
- `command` — `"get_memory"`
- `id` — UUID of the memory

**Example:**
```bash
curl -s -X POST "https://n8n.example.com/webhook/zikra" \
  -H "Authorization: Bearer velt-abc123" \
  -H "Content-Type: application/json" \
  -H "User-Agent: curl/7.81.0" \
  -d '{
    "command": "get_memory",
    "id":      "3f2a1b4c-8d7e-4c9b-a1f2-0e3d5c6b7a8f"
  }'
```

**Response:**
```json
{
  "id":          "3f2a1b4c-...",
  "project":     "myproject",
  "memory_type": "decision",
  "title":       "use pgvector for semantic search",
  "content_md":  "...",
  "tags":        ["database", "search"],
  "confidence":  0.95,
  "access_count": 12,
  "created_at":  "2026-01-15T10:30:00Z",
  "updated_at":  "2026-02-01T09:00:00Z"
}
```

---

## get_schema

Returns database introspection data: engine type, table names, and DDL for each
table. Does not search memories.

**Required fields:**
- `command` — `"get_schema"`

**Example:**
```bash
curl -s -X POST "https://n8n.example.com/webhook/zikra" \
  -H "Authorization: Bearer velt-abc123" \
  -H "Content-Type: application/json" \
  -H "User-Agent: curl/7.81.0" \
  -d '{"command": "get_schema"}'
```

**Response:**
```json
{
  "engine": "sqlite",
  "tables": ["memories", "prompt_runs", "error_log", "access_tokens"],
  "schema": {
    "memories": "CREATE TABLE memories (...)"
  }
}
```

---

## save_requirement

Save a product requirement or user story as a memory with memory_type=`"requirement"`.

**Required fields:**
- `command` — `"save_requirement"`
- `project` — string
- `title` — string, requirement name
- `content_md` — string, full requirement description
- `created_by` — string

**Optional fields:**
- `module` — string
- `tags` — array or null

**Example:**
```bash
curl -s -X POST "https://n8n.example.com/webhook/zikra" \
  -H "Authorization: Bearer velt-abc123" \
  -H "Content-Type: application/json" \
  -H "User-Agent: curl/7.81.0" \
  -d '{
    "command":     "save_requirement",
    "project":     "myproject",
    "title":       "users can reset password via email",
    "content_md":  "As a user, I want to reset my password by receiving a time-limited reset link via email so that I can regain access if I forget my password.\n\nAcceptance criteria:\n- Link expires after 1 hour\n- Link is single-use\n- User is shown confirmation page after reset",
    "created_by":  "dev-machine-01",
    "module":      "auth"
  }'
```

**Response:**
```json
{
  "id":     "5b9c3d1e-...",
  "status": "saved"
}
```

---

## list_requirements

List all requirements for a project, optionally filtered by module or status.

**Required fields:**
- `command` — `"list_requirements"`
- `project` — string

**Optional fields:**
- `module` — string
- `status` — `"active"` | `"archived"` (default: `"active"`)

**Example:**
```bash
curl -s -X POST "https://n8n.example.com/webhook/zikra" \
  -H "Authorization: Bearer velt-abc123" \
  -H "Content-Type: application/json" \
  -H "User-Agent: curl/7.81.0" \
  -d '{
    "command": "list_requirements",
    "project": "myproject",
    "module":  "auth"
  }'
```

**Response:**
```json
{
  "requirements": [
    {
      "id":          "5b9c3d1e-...",
      "title":       "users can reset password via email",
      "module":      "auth",
      "status":      "active",
      "created_at":  "2026-01-20T14:00:00Z"
    }
  ],
  "count": 1
}
```

---

## promote_requirement

Promotes a requirement to another memory_type (default: `"prompt"`). Looks up
by `id` (UUID) or `title`.

**Required fields:**
- `command` — `"promote_requirement"`
- `id` or `title` — UUID or title of the requirement memory

**Optional fields:**
- `promote_to` — string, target memory_type (default: `"prompt"`)

**Example:**
```bash
curl -s -X POST "https://n8n.example.com/webhook/zikra" \
  -H "Authorization: Bearer velt-abc123" \
  -H "Content-Type: application/json" \
  -H "User-Agent: curl/7.81.0" \
  -d '{
    "command": "promote_requirement",
    "id":      "5b9c3d1e-..."
  }'
```

**Response:**
```json
{
  "id":     "5b9c3d1e-...",
  "status": "promoted"
}
```

---

## create_token

Create a new bearer token. Requires an existing owner-role token for authorization.

**Required role:** owner

**Required fields:**
- `command` — `"create_token"`
- `label` — string, human-readable description of the token's purpose
- `role` — `"admin"` | `"developer"` | `"viewer"`

**Example:**
```bash
curl -s -X POST "https://n8n.example.com/webhook/zikra" \
  -H "Authorization: Bearer velt-OWNER-TOKEN" \
  -H "Content-Type: application/json" \
  -H "User-Agent: curl/7.81.0" \
  -d '{
    "command": "create_token",
    "label":   "CI/CD pipeline",
    "role":    "developer"
  }'
```

**Response:**
```json
{
  "status": "created",
  "token":  "token-7f3a9b2c4d1e8f5a",
  "label":  "CI/CD pipeline",
  "role":   "developer"
}
```

> The `token` value is shown only once. Store it securely immediately.
