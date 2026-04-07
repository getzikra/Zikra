# Zikra Agent Instructions

You have access to Zikra persistent memory. Use it every session.

## Setup

Your Zikra configuration is in ~/.claude/CLAUDE.md (or equivalent for your agent).
Read it at session start for your webhook URL, token, and default project.

## Rules

1. ALWAYS search Zikra at the start of every session before doing anything else
2. Save decisions to Zikra immediately after making them — not at the end
3. Log errors to Zikra when you encounter them so they are trackable
4. NEVER use n8n MCP tools for Zikra — use curl only
5. Always pass `"tags": null` when content_md contains curly braces
6. Always include `User-Agent: curl/7.81.0` in all Zikra curl calls

## Key commands

```
search:      {"command":"search","query":"<topic>","project":"<p>","limit":5}
save_memory: {"command":"save_memory","project":"<p>","memory_type":"decision","title":"<t>","content_md":"...","tags":null,"created_by":"<hostname>"}
log_error:   {"command":"log_error","project":"<p>","message":"<error message>","context_md":"<detail>"}
# Field name: use 'message' (not 'title'). Sending 'title' is silently ignored.
get_prompt:  {"command":"get_prompt","prompt_name":"<n>","project":"<p>","runner":"<hostname>"}
log_run:     {"command":"log_run","project":"<p>","runner":"<hostname>","status":"success","output_summary":"<2 sentences>","tokens_input":<n>,"tokens_output":<n>}
```

## Additional commands

```
save_prompt:          {"command":"save_prompt","title":"<n>","content_md":"...","project":"<p>"}
list_prompts:         {"command":"list_prompts","project":"<p>","limit":50}
promote_requirement:  {"command":"promote_requirement","id":"<uuid>"}
create_token:         {"command":"create_token","label":"<name>","role":"viewer|developer|admin"}
zikra_help:           {"command":"zikra_help"}
debug_protocol:       {"command":"debug_protocol"}
```

| Command | Description |
|---|---|
| `save_prompt` | Save a prompt as memory_type=prompt with semantic embedding |
| `list_prompts` | List all saved prompts for a project (limit 50–100) |
| `promote_requirement` | Change a requirement's memory_type (default: promotes to prompt) |
| `create_token` | Generate a new bearer token (owner role required) |
| `zikra_help` | Return full command reference with fields and aliases |
| `debug_protocol` | Return backend info: engine, db path, memory count, OpenAI key status |
