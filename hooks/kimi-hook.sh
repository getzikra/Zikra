#!/usr/bin/env bash
# kimi-hook.sh v1
# Kimi CLI / Kimi Code CLI hook handler for Stop and SessionEnd events.
# Uploads the session transcript tail to Zikra for server-side distillation
# and logs the run (with token totals when present in the transcript).
#
# Kimi hooks speak the same stdin JSON protocol as Claude Code
# (session_id, cwd, hook_event_name), but sessions live under
# ~/.kimi/sessions/<workdir-hash>/<session-id>/context.jsonl   (kimi-cli)
# ~/.kimi-code/sessions/<key>/<session-id>/agents/main/wire.jsonl (kimi-code)
#
# Register in ~/.kimi/config.toml:
#   [[hooks]]
#   event = "Stop"
#   command = "/home/you/.claude/hooks/kimi-hook.sh"
#
# Canonical source: zikra/hooks/kimi-hook.sh

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

SESSION_ID="$(printf '%s' "$PAYLOAD" | python3 -c \
  "import sys,json; d=json.load(sys.stdin); print(d.get('session_id',''))" \
  2>/dev/null || echo "")"
HOOK_CWD="$(printf '%s' "$PAYLOAD" | python3 -c \
  "import sys,json; d=json.load(sys.stdin); print(d.get('cwd',''))" \
  2>/dev/null || echo "")"
SID8="${SESSION_ID:0:8}"

# Project detection (shared helper when installed)
for _pd in "$HOME/.claude/zikra-project.sh" "$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)/zikra-project.sh"; do
  [[ -f "$_pd" ]] && { source "$_pd"; break; }
done
if [[ -n "$HOOK_CWD" ]] && declare -f zikra_detect_project >/dev/null; then
  DEFAULT_PROJECT="$(zikra_detect_project "$HOOK_CWD" "$DEFAULT_PROJECT")"
fi

# ── Locate the Kimi transcript for this session ───────────────────────────────
TRANSCRIPT=""
if [[ -n "$SESSION_ID" ]]; then
  for base in "${KIMI_SHARE_DIR:-$HOME/.kimi}/sessions" "${KIMI_CODE_HOME:-$HOME/.kimi-code}/sessions"; do
    [[ -d "$base" ]] || continue
    for cand in "$base"/*/"$SESSION_ID"/context.jsonl \
                "$base"/*/"$SESSION_ID"/agents/main/wire.jsonl; do
      [[ -f "$cand" ]] && { TRANSCRIPT="$cand"; break 2; }
    done
  done
fi
# Fallback: most recently modified Kimi transcript
if [[ -z "$TRANSCRIPT" ]]; then
  TRANSCRIPT="$(find "${KIMI_SHARE_DIR:-$HOME/.kimi}/sessions" \
                     "${KIMI_CODE_HOME:-$HOME/.kimi-code}/sessions" \
                -name 'context.jsonl' -o -name 'wire.jsonl' 2>/dev/null \
                | xargs ls -t 2>/dev/null | head -1)"
fi
[[ -z "$TRANSCRIPT" || ! -f "$TRANSCRIPT" ]] && exit 0

# Per-session cooldown (Stop can fire per response)
ZIKRA_TMP="/tmp"; [[ -d /tmp && -w /tmp ]] || ZIKRA_TMP="$HOME/.zikra"
SENTINEL="${ZIKRA_TMP}/.zikra_kimi_sentinel"
[[ -n "$SID8" ]] && SENTINEL="${SENTINEL}_${SID8}"
NOW="$(date +%s)"
if [[ -f "$SENTINEL" ]]; then
  LAST="$(cat "$SENTINEL" 2>/dev/null || echo 0)"
  [[ $(( NOW - LAST )) -lt 120 ]] && exit 0
fi
echo "$NOW" > "$SENTINEL"
find "$ZIKRA_TMP" -maxdepth 1 -name '.zikra_kimi_sentinel*' -mmin +1440 -delete 2>/dev/null || true

(
  # ── Upload tail for server-side distillation ────────────────────────────
  DISTILLED=0
  INGEST_TMP="$(mktemp "${ZIKRA_TMP}/.zikra_kimi_ingest.XXXXXX" 2>/dev/null)"
  if [[ -n "$INGEST_TMP" ]]; then
    tail -200 "$TRANSCRIPT" 2>/dev/null | head -c 200000 | python3 -c "
import json, sys
body = {
    'command': 'ingest_session',
    'project': sys.argv[1],
    'runner':  sys.argv[2],
    'transcript_tail': sys.stdin.read(),
}
if sys.argv[3]:
    body['session_id'] = sys.argv[3]
if sys.argv[4]:
    body['cwd'] = sys.argv[4]
json.dump(body, open(sys.argv[5], 'w'))" \
      "$DEFAULT_PROJECT" "$HOSTNAME_SHORT" "$SESSION_ID" "$HOOK_CWD" "$INGEST_TMP" 2>/dev/null
    if [[ -s "$INGEST_TMP" ]]; then
      RESP="$(curl -s -X POST "$ZIKRA_URL" \
        -H "Authorization: Bearer $ZIKRA_TOKEN" \
        -H "Content-Type: application/json" \
        -H "User-Agent: $ZIKRA_USER_AGENT" \
        --connect-timeout 15 --max-time 30 \
        --data-binary @"$INGEST_TMP" 2>/dev/null)"
      [[ "$RESP" == *'"queued"'* ]] && DISTILLED=1
    fi
    rm -f "$INGEST_TMP"
  fi

  # ── Fallback: no server distiller → save the last assistant reply ────────
  if [[ "$DISTILLED" -eq 0 ]]; then
    SUMMARY="$(python3 -c "
import json, sys
last = ''
try:
    for line in open(sys.argv[1], errors='replace'):
        try:
            e = json.loads(line)
        except Exception:
            continue
        msg = e.get('message') or e
        role = e.get('role') or msg.get('role') or e.get('type') or ''
        if role == 'assistant':
            c = msg.get('content') or e.get('content') or ''
            if isinstance(c, list):
                c = ' '.join(b.get('text', '') for b in c if isinstance(b, dict))
            if isinstance(c, str) and c.strip():
                last = c.strip()
except Exception:
    pass
print(last[:800])" "$TRANSCRIPT" 2>/dev/null)"
    if [[ -n "$SUMMARY" ]]; then
      TITLE="kimi:$(date +%Y-%m-%d):${SID8:-$(date +%H%M)}:${HOSTNAME_SHORT}"
      BODY="$(python3 -c "
import json, sys
print(json.dumps({
    'command': 'save_memory', 'project': sys.argv[1],
    'memory_type': 'conversation', 'title': sys.argv[2],
    'content_md': sys.argv[3], 'tags': None, 'created_by': sys.argv[4],
}))" "$DEFAULT_PROJECT" "$TITLE" "$SUMMARY" "$HOSTNAME_SHORT" 2>/dev/null)"
      [[ -n "$BODY" ]] && curl -s -X POST "$ZIKRA_URL" \
        -H "Authorization: Bearer $ZIKRA_TOKEN" \
        -H "Content-Type: application/json" \
        -H "User-Agent: $ZIKRA_USER_AGENT" \
        --connect-timeout 15 --max-time 20 \
        -d "$BODY" >/dev/null 2>&1
    fi
  fi

  # ── log_run with best-effort token totals ────────────────────────────────
  read T_IN T_OUT T_CR T_CC <<< $(python3 -c "
import json, sys
ti = to = cr = cc = 0
try:
    for line in open(sys.argv[1], errors='replace'):
        try:
            e = json.loads(line)
        except Exception:
            continue
        u = e.get('usage') or (e.get('message') or {}).get('usage') or {}
        if isinstance(u, dict):
            ti += u.get('input_tokens', 0) or 0
            to += u.get('output_tokens', 0) or 0
            cr += u.get('cache_read_input_tokens', u.get('cached_tokens', 0)) or 0
            cc += u.get('cache_creation_input_tokens', 0) or 0
except Exception:
    pass
print(ti, to, cr, cc)" "$TRANSCRIPT" 2>/dev/null)
  T_IN=${T_IN:-0}; T_OUT=${T_OUT:-0}; T_CR=${T_CR:-0}; T_CC=${T_CC:-0}

  RUN_BODY="$(python3 -c "
import json, sys
body = {
  'command': 'log_run', 'project': sys.argv[1], 'runner': sys.argv[2],
  'status': 'success',
  'output_summary': 'kimi session' + (' (queued for distillation)' if sys.argv[8] == '1' else ''),
  'tokens_input': int(sys.argv[3]), 'tokens_output': int(sys.argv[4]),
  'tokens_cache_read': int(sys.argv[5]), 'tokens_cache_creation': int(sys.argv[6]),
}
if sys.argv[7]:
    body['session_id'] = sys.argv[7]
print(json.dumps(body))" \
    "$DEFAULT_PROJECT" "$HOSTNAME_SHORT" "$T_IN" "$T_OUT" "$T_CR" "$T_CC" \
    "$SESSION_ID" "$DISTILLED" 2>/dev/null)"
  [[ -n "$RUN_BODY" ]] && curl -s -X POST "$ZIKRA_URL" \
    -H "Authorization: Bearer $ZIKRA_TOKEN" \
    -H "Content-Type: application/json" \
    -H "User-Agent: $ZIKRA_USER_AGENT" \
    --connect-timeout 15 --max-time 20 \
    -d "$RUN_BODY" >/dev/null 2>&1

  # Refresh the shared statusline cache if the stats updater is installed
  STATS="$HOME/.claude/hooks/zikra-stats-update.sh"
  [[ -f "$STATS" ]] && printf '%s' "$PAYLOAD" | bash "$STATS" >/dev/null 2>&1
) >> "$HOME/.zikra/hook_errors.log" 2>&1 &
disown

exit 0
