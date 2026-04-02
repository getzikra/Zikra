#!/bin/bash
# Zikra stats updater — runs on Stop hook to bump runs_today counter

CACHE="$HOME/.claude/cache/zikra-stats.json"
mkdir -p "$HOME/.claude/cache"

python3 - <<'PYEOF'
import json, os, datetime

cache_path = os.path.expanduser('~/.claude/cache/zikra-stats.json')

try:
    with open(cache_path) as f:
        stats = json.load(f)
except:
    stats = {"runs_today": 0, "runs_total": 0, "memory_count": 0, "last_saved": None, "project": "global"}

# Check if we need to reset daily counter
today = datetime.date.today().isoformat()
last_saved = stats.get("last_saved", "")[:10] if stats.get("last_saved") else ""

if last_saved != today:
    stats["runs_today"] = 0

stats["runs_today"] = stats.get("runs_today", 0) + 1
stats["runs_total"] = stats.get("runs_total", 0) + 1
stats["last_saved"] = datetime.datetime.now().isoformat()

with open(cache_path, 'w') as f:
    json.dump(stats, f)
PYEOF
