#!/bin/bash
# Zikra stats updater — runs on Stop hook to bump runs_today counter

CACHE="$HOME/.claude/cache/zikra-stats.json"
ZIKRA_URL="${ZIKRA_URL:-$(grep ZIKRA_URL "$HOME/.zikra/token" 2>/dev/null | cut -d= -f2)}"
ZIKRA_TOKEN="${ZIKRA_TOKEN:-$(grep ZIKRA_TOKEN "$HOME/.zikra/token" 2>/dev/null | cut -d= -f2)}"
mkdir -p "$HOME/.claude/cache"

# Normalize URL: strip trailing slash, append suffix only if not already present
_SUFFIX="/webhook/zikra"
ZIKRA_URL="${ZIKRA_URL%/}"
[[ "$ZIKRA_URL" != *"$_SUFFIX" ]] && ZIKRA_URL="${ZIKRA_URL}${_SUFFIX}"

# Fetch live memory count from Zikra (search with max_results=1 returns total)
MEMORY_COUNT=$(curl -s -X POST "$ZIKRA_URL" \
  -H "Authorization: Bearer $ZIKRA_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command":"search","query":"*","max_results":1}' \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('total', d.get('count', 0)))" 2>/dev/null || echo "0")

python3 - "$MEMORY_COUNT" <<'PYEOF'
import json, os, datetime, sys

cache_path = os.path.expanduser('~/.claude/cache/zikra-stats.json')
memory_count_arg = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 0

try:
    with open(cache_path) as f:
        stats = json.load(f)
except:
    stats = {"runs_today": 0, "runs_total": 0, "memory_count": 0, "updated_at": None, "project": "global"}

# Check if we need to reset daily counter
today = datetime.date.today().isoformat()
last_saved = stats.get("updated_at", "")[:10] if stats.get("updated_at") else ""

if last_saved != today:
    stats["runs_today"] = 0

stats["runs_today"] = stats.get("runs_today", 0) + 1
stats["runs_total"] = stats.get("runs_total", 0) + 1
stats["updated_at"] = datetime.datetime.now().isoformat()
# Update memory_count if we got a valid value; preserve previous value otherwise
if memory_count_arg > 0:
    stats["memory_count"] = memory_count_arg

with open(cache_path, 'w') as f:
    json.dump(stats, f)
PYEOF
