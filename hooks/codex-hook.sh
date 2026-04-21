#!/bin/bash
# Zikra Codex CLI hook
# Register for Stop and PostToolUse events.
#
# Codex uses ~/.codex/config.toml. Add a [hooks] section:
#
#   [hooks]
#   Stop        = ["/path/to/codex-hook.sh"]
#   PostToolUse = ["/path/to/codex-hook.sh"]
#
# If your version uses hooks.json instead, add:
#   {
#     "Stop":        [{"command": "/path/to/codex-hook.sh"}],
#     "PostToolUse": [{"command": "/path/to/codex-hook.sh"}]
#   }
#
# Codex pipes a JSON payload to stdin. This script:
#   1. Extracts transcript_path, cwd, model from that payload
#   2. Parses the transcript (history.jsonl) for token counts
#   3. Updates ~/.claude/cache/zikra-stats.json (shared with Claude Code)

TOKEN_FILE="$HOME/.zikra/token"
ZIKRA_TOKEN="${ZIKRA_TOKEN:-$(grep ^ZIKRA_TOKEN "$TOKEN_FILE" 2>/dev/null | cut -d= -f2-)}"
ZIKRA_URL="${ZIKRA_URL:-$(grep ^ZIKRA_URL "$TOKEN_FILE" 2>/dev/null | cut -d= -f2-)}"
ZIKRA_PROJECT="${ZIKRA_PROJECT:-$(grep ^ZIKRA_PROJECT "$TOKEN_FILE" 2>/dev/null | cut -d= -f2-)}"
CACHE="$HOME/.claude/cache/zikra-stats.json"
mkdir -p "$HOME/.claude/cache"

PAYLOAD=$(cat 2>/dev/null || echo '{}')

python3 - "$CACHE" "${ZIKRA_PROJECT:-global}" <<PYEOF
import json, sys, os, datetime

cache_path      = sys.argv[1]
default_project = sys.argv[2]

payload = json.loads("""$PAYLOAD""" or '{}')

transcript_path = payload.get('transcript_path', '')
cwd             = payload.get('cwd', '')
model           = payload.get('model', 'codex')
event           = payload.get('hook_event_name', '')

# ── Project detection ────────────────────────────────────────────────────────
def detect_project_from_cwd(cwd, fallback):
    import re, pathlib
    home = pathlib.Path.home()
    d = pathlib.Path(cwd).resolve() if cwd else home
    seen = set()
    pat = re.compile(r'^\s*(?:-\s*)?project\s*[:=]\s*["\']?([a-zA-Z0-9_\-]+)["\']?', re.I | re.M)
    env = re.compile(r'ZIKRA_PROJECT\s*=\s*["\']?([a-zA-Z0-9_\-]+)["\']?', re.I)
    while d not in seen:
        seen.add(d)
        md = d / 'CLAUDE.md'
        if md.exists():
            try:
                text = md.read_text()
                for r in (pat, env):
                    m = r.search(text)
                    if m and m.group(1).lower() not in ('', 'global'):
                        return m.group(1).lower()
            except: pass
        parent = d.parent
        if parent == d or d == home or str(d) == '/':
            break
        d = parent
    return fallback

project = detect_project_from_cwd(cwd, default_project)

# ── Transcript parsing ───────────────────────────────────────────────────────
# Codex stores history as history.jsonl in the session directory.
# The payload may give transcript_path directly, or we infer from session_id.
# Token counts appear in OpenAI-style usage objects.
tokens_in = 0
tokens_out = 0

# Resolve transcript path: use provided path, or look next to it
paths_to_try = []
if transcript_path:
    paths_to_try.append(transcript_path)
    # Also try history.jsonl in same dir
    paths_to_try.append(os.path.join(os.path.dirname(transcript_path), 'history.jsonl'))

session_id = payload.get('session_id', '')
if session_id:
    base = os.path.expanduser(f'~/.codex/sessions/{session_id}')
    paths_to_try += [f'{base}/history.jsonl', f'{base}.jsonl']

for path in paths_to_try:
    if not path or not os.path.exists(path):
        continue
    try:
        with open(path, encoding='utf-8', errors='ignore') as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    # OpenAI-style usage
                    usage = entry.get('usage') or {}
                    tokens_in  += usage.get('prompt_tokens', usage.get('input_tokens', 0))
                    tokens_out += usage.get('completion_tokens', usage.get('output_tokens', 0))
                    # Nested under choices[0].usage or similar
                    for choice in entry.get('choices', []):
                        u = choice.get('usage') or {}
                        tokens_in  += u.get('prompt_tokens', 0)
                        tokens_out += u.get('completion_tokens', 0)
                except Exception:
                    pass
        if tokens_in or tokens_out:
            break
    except Exception:
        pass

# ── Update shared cache ──────────────────────────────────────────────────────
try:
    with open(cache_path) as fh:
        stats = json.load(fh)
except Exception:
    stats = {}

today = datetime.date.today().isoformat()
if (stats.get('updated_at') or '')[:10] != today:
    stats['runs_today'] = 0

stats['runs_today']   = stats.get('runs_today', 0) + 1
stats['runs_total']   = stats.get('runs_total', 0) + 1
stats['updated_at']   = datetime.datetime.now().isoformat()
stats['project']      = project
stats['last_tool']    = 'codex'
stats['last_model']   = model
if tokens_in:
    stats['last_tokens_in']  = tokens_in
if tokens_out:
    stats['last_tokens_out'] = tokens_out

os.makedirs(os.path.dirname(cache_path), exist_ok=True)
with open(cache_path, 'w') as fh:
    json.dump(stats, fh)
PYEOF
