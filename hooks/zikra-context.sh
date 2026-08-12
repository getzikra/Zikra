#!/usr/bin/env bash
# zikra-context.sh v2
# Claude Code SessionStart hook — auto-recall.
# Fetches a token-budgeted project briefing from Zikra (get_context) and
# injects it as additionalContext, so every session starts already knowing
# the project's pinned memories, recent decisions, and open bugs.
#
# Fails silent and fast: a dead Zikra server must never delay session start.
#
# Canonical source: zikra/hooks/zikra-context.sh

ZIKRA_URL="ZIKRA_URL_PLACEHOLDER"
ZIKRA_TOKEN="ZIKRA_TOKEN_PLACEHOLDER"
DEFAULT_PROJECT="DEFAULT_PROJECT_PLACEHOLDER"
ZIKRA_USER_AGENT="curl/7.81.0"
CONTEXT_TOKENS="${ZIKRA_CONTEXT_TOKENS:-1500}"

# --plain: print raw markdown instead of Claude's hookSpecificOutput JSON.
# Kimi CLI adds exit-0 stdout to context directly, so it gets --plain.
PLAIN=0
[[ "${1:-}" == "--plain" ]] && PLAIN=1

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

PAYLOAD="$(cat 2>/dev/null || echo '{}')"

HOOK_CWD="$(printf '%s' "$PAYLOAD" | python3 -c \
  "import sys,json; d=json.load(sys.stdin); print(d.get('cwd',''))" \
  2>/dev/null || echo "")"

# Project detection: A2K_PROJECT, nearest manifest, then legacy fallback.
for _project_helper in \
  "$HOME/.claude/zikra-project.sh" \
  "$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)/zikra-project.sh"; do
  if [[ -f "$_project_helper" ]]; then
    # shellcheck disable=SC1090
    source "$_project_helper"
    DEFAULT_PROJECT="$(zikra_detect_project "$HOOK_CWD" "$DEFAULT_PROJECT")"
    break
  fi
done
unset _project_helper

BODY="$(python3 -c "
import json, sys
print(json.dumps({
    'command':    'get_context',
    'project':    sys.argv[1],
    'max_tokens': int(sys.argv[2]),
}))" "$DEFAULT_PROJECT" "$CONTEXT_TOKENS" 2>/dev/null)"
[[ -z "$BODY" ]] && exit 0

RESP="$(curl -s -X POST "$ZIKRA_URL" \
  -H "Authorization: Bearer $ZIKRA_TOKEN" \
  -H "Content-Type: application/json" \
  -H "User-Agent: $ZIKRA_USER_AGENT" \
  --connect-timeout 3 --max-time 8 \
  -d "$BODY" 2>/dev/null)"
[[ -z "$RESP" ]] && exit 0

# Emit hookSpecificOutput.additionalContext (or raw markdown with --plain);
# empty/errored responses exit silently
printf '%s' "$RESP" | python3 -c "
import json, sys
plain = sys.argv[1] == '1'
try:
    d = json.load(sys.stdin)
    ctx = d.get('context_md') or ''
    if not ctx.strip() or d.get('memories_used', 0) == 0:
        sys.exit(0)
    if plain:
        print(ctx)
    else:
        print(json.dumps({
            'hookSpecificOutput': {
                'hookEventName': 'SessionStart',
                'additionalContext': ctx,
            }
        }))
except Exception:
    sys.exit(0)
" "$PLAIN" 2>/dev/null

exit 0
