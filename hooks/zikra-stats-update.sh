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

# Detect project from CWD so the memory-count query can be scoped to the
# current project. Explicit map entries or built-in inference are required.
for _pd in "$HOME/.claude/zikra-project.sh" "$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)/zikra-project.sh"; do
  [[ -f "$_pd" ]] && { source "$_pd"; break; }
done
if ! declare -f zikra_detect_project >/dev/null; then
  echo "[zikra-stats] project detector unavailable; skipping" >&2
  exit 0
fi
if ! DETECTED_PROJECT="$(zikra_detect_project "$HOOK_CWD")" || [[ -z "$DETECTED_PROJECT" ]]; then
  echo "[zikra-stats] unmapped or missing cwd; skipping: ${HOOK_CWD:-[missing]}" >&2
  exit 0
fi
PROJECT="$DETECTED_PROJECT"

# Fetch live memory count from Zikra, scoped to the current project so the
# '187 memories' tag actually reflects what's visible in this project. When
# PROJECT resolves to 'global', the server treats it as a wildcard and
# returns the cross-project total (the same behavior as before).
MEMORY_COUNT=$(curl -s --max-time 3 --connect-timeout 2 -X POST "$ZIKRA_URL" \
  -H "Authorization: Bearer $ZIKRA_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"command\":\"search\",\"query\":\"*\",\"limit\":1,\"project\":\"$PROJECT\"}" \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('total', d.get('count', 0)))" 2>/dev/null || echo "0")

# Fetch server version
SERVER_VERSION=$(curl -s --max-time 3 --connect-timeout 2 -X POST "$ZIKRA_URL" \
  -H "Authorization: Bearer $ZIKRA_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command":"version"}' \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('version',''))" 2>/dev/null || echo "")

# Fetch orphan/stale count for statusline warning. Silent fail on older
# servers that don't know the hygiene_report command.
ORPHAN_COUNT=$(curl -s --max-time 3 --connect-timeout 2 -X POST "$ZIKRA_URL" \
  -H "Authorization: Bearer $ZIKRA_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"command\":\"hygiene_report\",\"project\":\"$PROJECT\",\"stale_days\":30}" \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('orphan_count',0))" 2>/dev/null || echo "0")

python3 - "$MEMORY_COUNT" "$HOOK_CWD" "$PROJECT" "$SERVER_VERSION" "$ORPHAN_COUNT" <<'PYEOF'
import json, os, datetime, sys, socket

cache_path = os.path.expanduser('~/.claude/cache/zikra-stats.json')
memory_count_arg   = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 0
hook_cwd           = sys.argv[2] if len(sys.argv) > 2 else ''
default_project    = sys.argv[3] if len(sys.argv) > 3 else 'global'
server_version_arg = sys.argv[4].strip() if len(sys.argv) > 4 else ''
orphan_count_arg   = int(sys.argv[5]) if len(sys.argv) > 5 and sys.argv[5].lstrip('-').isdigit() else 0

# Project is resolved in bash via the shared zikra-project.sh helper
project = default_project

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

# Always refresh orphan_count (0 is a valid state, not "missing data")
stats["orphan_count"] = max(0, orphan_count_arg)

# Cache server version if we got one
if server_version_arg:
    v = server_version_arg if server_version_arg.startswith('v') else f'v{server_version_arg}'
    stats["server_version"] = v

# Check latest Zikra version from GitHub once per day (for update comparison)
version_checked = stats.get("version_checked", "")
if version_checked != today:
    try:
        import urllib.request
        req = urllib.request.Request(
            "https://api.github.com/repos/getzikra/zikra/tags",
            headers={"User-Agent": "zikra-stats/1.0"}
        )
        resp = urllib.request.urlopen(req, timeout=3)
        tags = json.loads(resp.read().decode())
        if tags and isinstance(tags, list) and "name" in tags[0]:
            stats["latest_version"] = tags[0]["name"]
        stats["version_checked"] = today
    except:
        pass  # silent fail — keep previous cached value

# Atomic write: serialize to a PER-PROCESS temp file in the same dir, fsync,
# then os.replace. os.replace is atomic on POSIX, so the statusline reader can
# never observe a half-written cache even if this process is killed by the hook
# timeout. The pid suffix keeps concurrent Stop hooks (multiple terminals
# closing at once) from colliding on a shared temp path.
tmp_path = '%s.tmp.%d' % (cache_path, os.getpid())
try:
    with open(tmp_path, 'w') as f:
        json.dump(stats, f)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, cache_path)
finally:
    try:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
    except OSError:
        pass
PYEOF
