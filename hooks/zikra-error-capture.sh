#!/usr/bin/env bash
# zikra-error-capture.sh v1
# Claude Code PostToolUse hook (Bash matcher) — automatic error capture.
# When a shell command fails with a recognizable error, logs it to Zikra
# (log_error). The server promotes errors recurring 3+ times in a week
# into searchable 'bug' memories.
#
# Local dedup: the same command+error is reported at most once per 6 hours.
# Fails silent and never blocks the session.
#
# Canonical source: zikra/hooks/zikra-error-capture.sh

ZIKRA_URL="ZIKRA_URL_PLACEHOLDER"
ZIKRA_TOKEN="ZIKRA_TOKEN_PLACEHOLDER"
DEFAULT_PROJECT="DEFAULT_PROJECT_PLACEHOLDER"
ZIKRA_USER_AGENT="curl/7.81.0"

_ZIKRA_TOKEN_FILE="$HOME/.zikra/token"
if [[ -f "$_ZIKRA_TOKEN_FILE" ]]; then
  _load_kv() { grep "^$1=" "$_ZIKRA_TOKEN_FILE" 2>/dev/null | head -1 | cut -d= -f2-; }
  [[ "$ZIKRA_URL"       == *PLACEHOLDER* ]] && ZIKRA_URL="$(_load_kv ZIKRA_URL)"
  [[ "$ZIKRA_TOKEN"     == *PLACEHOLDER* ]] && ZIKRA_TOKEN="$(_load_kv ZIKRA_TOKEN)"
  [[ "$DEFAULT_PROJECT" == *PLACEHOLDER* ]] && DEFAULT_PROJECT="$(_load_kv ZIKRA_PROJECT)"
fi
[[ "$ZIKRA_URL"       == *PLACEHOLDER* ]] && ZIKRA_URL="${ZIKRA_URL_ENV:-}"
[[ "$ZIKRA_TOKEN"     == *PLACEHOLDER* ]] && ZIKRA_TOKEN="${ZIKRA_TOKEN_ENV:-}"
[[ "$DEFAULT_PROJECT" == *PLACEHOLDER* ]] && DEFAULT_PROJECT="${ZIKRA_PROJECT:-global}"
[[ -z "$ZIKRA_URL" || -z "$ZIKRA_TOKEN" ]] && exit 0

HOSTNAME_SHORT="$(hostname -s 2>/dev/null)" \
    || HOSTNAME_SHORT="$(hostname 2>/dev/null | cut -d. -f1)" \
    || HOSTNAME_SHORT="${HOSTNAME:-unknown}"
HOSTNAME_SHORT="${HOSTNAME_SHORT:-unknown}"

PAYLOAD="$(cat 2>/dev/null || echo '{}')"

HOOK_CWD="$(printf '%s' "$PAYLOAD" | python3 -c \
  "import sys,json; d=json.load(sys.stdin); print(d.get('cwd',''))" \
  2>/dev/null || echo "")"
for _pd in "$HOME/.claude/zikra-project.sh" "$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)/zikra-project.sh"; do
  [[ -f "$_pd" ]] && { source "$_pd"; break; }
done
if [[ -n "$HOOK_CWD" ]] && declare -f zikra_detect_project >/dev/null; then
  DEFAULT_PROJECT="$(zikra_detect_project "$HOOK_CWD" "$DEFAULT_PROJECT")"
fi

ERRDIR="$HOME/.zikra/errcache"
mkdir -p "$ERRDIR" 2>/dev/null

# Everything below runs in Python: parse payload, decide if it's a real
# error, dedup locally, and print the log_error body (or nothing).
BODY="$(printf '%s' "$PAYLOAD" | python3 -c "
import hashlib, json, os, re, sys, time

try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(0)

if d.get('tool_name') not in ('Bash', 'bash'):
    sys.exit(0)

tool_input = d.get('tool_input') or {}
command = (tool_input.get('command') or '').strip()
if not command:
    sys.exit(0)

resp = d.get('tool_response')
if isinstance(resp, dict):
    stdout = str(resp.get('stdout') or '')
    stderr = str(resp.get('stderr') or '')
    is_error = bool(resp.get('is_error') or resp.get('isError'))
    combined = stderr or stdout
elif isinstance(resp, list):
    combined = ' '.join(str(b.get('text', '')) for b in resp if isinstance(b, dict))
    stderr = combined
    is_error = False
else:
    combined = str(resp or '')
    stderr = combined
    is_error = False

ERROR_RE = re.compile(
    r'(traceback \(most recent call last\)|segmentation fault'
    r'|command not found|no such file or directory|permission denied'
    r'|fatal:|error:|exception:|panic:|cannot |failed to |assertion.?error'
    r'|module.?not.?found|syntax.?error|connection refused|exit code [1-9])',
    re.IGNORECASE)

m = ERROR_RE.search(combined)
if not (is_error or m):
    sys.exit(0)

lines = [l.strip() for l in combined.splitlines() if l.strip()]
first_error = next((l for l in lines if ERROR_RE.search(l)), lines[0] if lines else 'unknown error')

# Local dedup: same command head + error line at most once per 6h
key = hashlib.sha1((command[:120] + '|' + first_error[:200]).encode()).hexdigest()[:16]
cache = os.path.join(sys.argv[1], key)
now = time.time()
try:
    if now - os.path.getmtime(cache) < 6 * 3600:
        sys.exit(0)
except OSError:
    pass
try:
    open(cache, 'w').write(str(now))
    # prune cache entries older than 7 days
    for f in os.listdir(sys.argv[1]):
        p = os.path.join(sys.argv[1], f)
        try:
            if now - os.path.getmtime(p) > 7 * 86400:
                os.remove(p)
        except OSError:
            pass
except OSError:
    pass

body = {
    'command':    'log_error',
    'project':    sys.argv[2],
    'runner':     sys.argv[3],
    'error_type': 'bash',
    'message':    first_error[:300],
    'context_md': '**Command:**\n\`\`\`\n' + command[:500] + '\n\`\`\`\n\n**Output tail:**\n\`\`\`\n' + combined[-1500:] + '\n\`\`\`',
}
if d.get('session_id'):
    body['session_id'] = d['session_id']
print(json.dumps(body))
" "$ERRDIR" "$DEFAULT_PROJECT" "$HOSTNAME_SHORT" 2>/dev/null)"

[[ -z "$BODY" ]] && exit 0

(
  curl -s -X POST "$ZIKRA_URL" \
    -H "Authorization: Bearer $ZIKRA_TOKEN" \
    -H "Content-Type: application/json" \
    -H "User-Agent: $ZIKRA_USER_AGENT" \
    --connect-timeout 5 --max-time 10 \
    -d "$BODY" >/dev/null 2>&1
) &
disown

exit 0
