# g:sync_zikra

Run this at the start of every session to load context from persistent memory.

## What this does

1. Searches Zikra for recent decisions, errors, and active work
2. Loads your project context into the session
3. Confirms Zikra is reachable before you start work

## Execute now

Read your Zikra config from `~/.claude/CLAUDE.md`:
- `ZIKRA_URL` — webhook endpoint
- `ZIKRA_TOKEN` — bearer token
- `DEFAULT_PROJECT` — your default project name

Then run these searches in order:

### 1. Recent decisions
```bash
curl -s -X POST "$ZIKRA_URL" \
  -H "Authorization: Bearer $ZIKRA_TOKEN" \
  -H "Content-Type: application/json" \
  -H "User-Agent: curl/7.81.0" \
  -d '{
    "command":     "search",
    "query":       "recent decision architecture change",
    "project":     "'"$DEFAULT_PROJECT"'",
    "max_results": 5
  }'
```

### 2. Recent errors / bugs
```bash
curl -s -X POST "$ZIKRA_URL" \
  -H "Authorization: Bearer $ZIKRA_TOKEN" \
  -H "Content-Type: application/json" \
  -H "User-Agent: curl/7.81.0" \
  -d '{
    "command":     "search",
    "query":       "error bug broken failed",
    "project":     "'"$DEFAULT_PROJECT"'",
    "max_results": 3
  }'
```

### 3. Active work context
```bash
curl -s -X POST "$ZIKRA_URL" \
  -H "Authorization: Bearer $ZIKRA_TOKEN" \
  -H "Content-Type: application/json" \
  -H "User-Agent: curl/7.81.0" \
  -d '{
    "command":     "search",
    "query":       "in progress working on current task",
    "project":     "'"$DEFAULT_PROJECT"'",
    "max_results": 3
  }'
```

## After running

Read the results and summarize what you know about the current state of the project before doing anything else. If Zikra returns an error or is unreachable, note it and continue without memory — do not block on this.

## Expected behaviour

- If this is a fresh install: all searches return empty results. That is correct.
- If there are existing memories: summarize the top results as context for the session.
- If Zikra is down: log a warning and continue.
