#!/bin/bash
# Zikra Gemini CLI hook
# Register for AfterModel and SessionEnd events in ~/.gemini/settings.json:
#
#   {
#     "hooks": {
#       "AfterModel": [{"name":"zikra","command":"/path/to/gemini-hook.sh"}],
#       "SessionEnd":  [{"name":"zikra","command":"/path/to/gemini-hook.sh"}]
#     }
#   }
#
# Gemini pipes a JSON payload to stdin for each event. This script:
#   1. Extracts transcript_path, cwd, model from that payload
#   2. Parses the transcript for token counts
#   3. Updates ~/.claude/cache/zikra-stats.json (shared with Claude Code)
#   4. Optionally logs the run to the Zikra server if configured

TOKEN_FILE="$HOME/.zikra/token"
ZIKRA_TOKEN="${ZIKRA_TOKEN:-$(grep ^ZIKRA_TOKEN "$TOKEN_FILE" 2>/dev/null | cut -d= -f2-)}"
ZIKRA_URL="${ZIKRA_URL:-$(grep ^ZIKRA_URL "$TOKEN_FILE" 2>/dev/null | cut -d= -f2-)}"
ZIKRA_PROJECT="${ZIKRA_PROJECT:-$(grep ^ZIKRA_PROJECT "$TOKEN_FILE" 2>/dev/null | cut -d= -f2-)}"
CACHE="$HOME/.claude/cache/zikra-stats.json"
mkdir -p "$HOME/.claude/cache"

# Read hook payload from stdin (Gemini pipes JSON on each event)
PAYLOAD=$(cat 2>/dev/null || echo '{}')

python3 - "$CACHE" "${ZIKRA_PROJECT:-global}" "$ZIKRA_URL" "$ZIKRA_TOKEN" <<PYEOF
import json, sys, os, datetime

cache_path      = sys.argv[1]
default_project = sys.argv[2]
zikra_url       = sys.argv[3] if len(sys.argv) > 3 else ''
zikra_token     = sys.argv[4] if len(sys.argv) > 4 else ''

payload = json.loads("""$PAYLOAD""" or '{}')

transcript_path = payload.get('transcript_path', '')
cwd             = payload.get('cwd', '')
event           = payload.get('hook_event_name', '')
# AfterModel exposes the request under llm_request or similar
llm_req         = payload.get('llm_request') or {}
model           = llm_req.get('model', '') if isinstance(llm_req, dict) else ''
model           = model or payload.get('model', 'gemini')

# ── Project detection ────────────────────────────────────────────────────────
def detect_project_from_cwd(cwd, fallback):
    """Walk up from cwd looking for CLAUDE.md with project: <name>."""
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
# Gemini CLI stores conversations as JSONL. The exact schema varies by version;
# we probe several known field names so the hook works across releases.
tokens_in = 0
tokens_out = 0
if transcript_path and os.path.exists(transcript_path):
    try:
        with open(transcript_path, encoding='utf-8', errors='ignore') as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    # Primary: Gemini API usageMetadata
                    usage = entry.get('usageMetadata') or {}
                    tokens_in  += usage.get('promptTokenCount', 0)
                    tokens_out += usage.get('candidatesTokenCount', 0)
                    # Fallback: OpenAI-style usage object
                    if not usage:
                        usage = entry.get('usage') or {}
                        tokens_in  += usage.get('input_tokens', usage.get('prompt_tokens', 0))
                        tokens_out += usage.get('output_tokens', usage.get('completion_tokens', 0))
                except Exception:
                    pass
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
stats['last_tool']    = 'gemini'
stats['last_model']   = model
if tokens_in:
    stats['last_tokens_in']  = tokens_in
if tokens_out:
    stats['last_tokens_out'] = tokens_out

os.makedirs(os.path.dirname(cache_path), exist_ok=True)
with open(cache_path, 'w') as fh:
    json.dump(stats, fh)
PYEOF
