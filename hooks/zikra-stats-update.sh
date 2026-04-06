#!/bin/bash
# Zikra stats updater — runs on Stop hook to bump runs_today counter

CACHE="$HOME/.claude/cache/zikra-stats.json"
ZIKRA_URL="${ZIKRA_URL:-$(grep ZIKRA_URL "$HOME/.zikra/token" 2>/dev/null | cut -d= -f2)}"
ZIKRA_TOKEN="${ZIKRA_TOKEN:-$(grep ZIKRA_TOKEN "$HOME/.zikra/token" 2>/dev/null | cut -d= -f2)}"
ZIKRA_PROJECT="${ZIKRA_PROJECT:-$(grep ZIKRA_PROJECT "$HOME/.zikra/token" 2>/dev/null | cut -d= -f2)}"
mkdir -p "$HOME/.claude/cache"

# Normalize URL: strip trailing slash, append suffix only if not already present
_SUFFIX="/webhook/zikra"
ZIKRA_URL="${ZIKRA_URL%/}"
[[ "$ZIKRA_URL" != *"$_SUFFIX" ]] && ZIKRA_URL="${ZIKRA_URL}${_SUFFIX}"

# Read CWD from hook payload stdin for dynamic project detection
PAYLOAD="$(cat 2>/dev/null || echo '{}')"
HOOK_CWD="$(printf '%s' "$PAYLOAD" | python3 -c \
  "import sys,json; d=json.load(sys.stdin); print(d.get('cwd',''))" \
  2>/dev/null || echo "")"

# Fetch live memory count from Zikra (search with limit=1 returns total)
MEMORY_COUNT=$(curl -s -X POST "$ZIKRA_URL" \
  -H "Authorization: Bearer $ZIKRA_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command":"search","query":"*","limit":1}' \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('total', d.get('count', 0)))" 2>/dev/null || echo "0")

python3 - "$MEMORY_COUNT" "$HOOK_CWD" "${ZIKRA_PROJECT:-global}" <<'PYEOF'
import json, os, datetime, sys, socket

cache_path = os.path.expanduser('~/.claude/cache/zikra-stats.json')
memory_count_arg   = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 0
hook_cwd           = sys.argv[2] if len(sys.argv) > 2 else ''
default_project    = sys.argv[3] if len(sys.argv) > 3 else 'global'

def detect_project(cwd, fallback):
    c = cwd.lower()
    if 'getzikra' in c or '/zikra' in c: return 'zikra'
    if 'molten8'  in c:                  return 'molten8'
    if 'veltis'   in c:                  return 'veltisai'
    return fallback

project = detect_project(hook_cwd, default_project)

try:
    with open(cache_path) as f:
        stats = json.load(f)
except:
    stats = {"runs_today": 0, "runs_total": 0, "memory_count": 0, "updated_at": None, "project": project}

# Check if we need to reset daily counter
today = datetime.date.today().isoformat()
last_saved = stats.get("updated_at", "")[:10] if stats.get("updated_at") else ""

if last_saved != today:
    stats["runs_today"] = 0

stats["runs_today"] = stats.get("runs_today", 0) + 1
stats["runs_total"] = stats.get("runs_total", 0) + 1
stats["updated_at"] = datetime.datetime.now().isoformat()
stats["project"]    = project
# Update memory_count if we got a valid value; preserve previous value otherwise
if memory_count_arg > 0:
    stats["memory_count"] = memory_count_arg

with open(cache_path, 'w') as f:
    json.dump(stats, f)
PYEOF
