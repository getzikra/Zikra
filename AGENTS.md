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
search:      {"command":"search","query":"<topic>","project":"<p>","max_results":5}
save_memory: {"command":"save_memory","project":"<p>","memory_type":"decision","title":"<t>","content_md":"...","tags":null,"created_by":"<hostname>"}
log_error:   {"command":"log_error","project":"<p>","title":"<t>","content_md":"<detail>"}
get_prompt:  {"command":"get_prompt","prompt_name":"<n>","project":"<p>","runner":"<hostname>"}
log_run:     {"command":"log_run","project":"<p>","runner":"<hostname>","status":"success","output_summary":"<2 sentences>","tokens_input":<n>,"tokens_output":<n>,"tokens_cache_read":<n>,"tokens_cache_creation":<n>}
```
