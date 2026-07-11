#!/usr/bin/env bash
# zikra_autolog.sh v9
# Claude Code hook handler for Stop and PreCompact events.
# Saves session diary and pre-compact summaries to Zikra persistent memory.
#
# Invoked automatically by Claude Code hooks — never run manually.
# Works on: WSL, native Linux, macOS, Git Bash / MSYS on Windows.
#
# Canonical source: zikra/hooks/zikra_autolog.sh

ZIKRA_URL="ZIKRA_URL_PLACEHOLDER"
ZIKRA_TOKEN="ZIKRA_TOKEN_PLACEHOLDER"
DEFAULT_PROJECT="DEFAULT_PROJECT_PLACEHOLDER"
ZIKRA_USER_AGENT="curl/7.81.0"

# Load from ~/.zikra/token if install.sh hasn't patched the placeholders yet
_ZIKRA_TOKEN_FILE="$HOME/.zikra/token"
if [[ -f "$_ZIKRA_TOKEN_FILE" ]]; then
  _load_kv() { grep "^$1=" "$_ZIKRA_TOKEN_FILE" 2>/dev/null | head -1 | cut -d= -f2-; }
  [[ "$ZIKRA_URL"       == *PLACEHOLDER* ]] && ZIKRA_URL="$(_load_kv ZIKRA_URL)"
  [[ "$ZIKRA_TOKEN"     == *PLACEHOLDER* ]] && ZIKRA_TOKEN="$(_load_kv ZIKRA_TOKEN)"
  [[ "$DEFAULT_PROJECT" == *PLACEHOLDER* ]] && DEFAULT_PROJECT="$(_load_kv ZIKRA_PROJECT)"
fi
# Also honour plain env vars as a last resort
[[ "$ZIKRA_URL"       == *PLACEHOLDER* ]] && ZIKRA_URL="${ZIKRA_URL_ENV:-$ZIKRA_URL}"
[[ "$ZIKRA_TOKEN"     == *PLACEHOLDER* ]] && ZIKRA_TOKEN="${ZIKRA_TOKEN_ENV:-$ZIKRA_TOKEN}"
[[ "$DEFAULT_PROJECT" == *PLACEHOLDER* ]] && DEFAULT_PROJECT="${ZIKRA_PROJECT:-global}"

# ── Environment detection ─────────────────────────────────────────────────────
detect_shell_env() {
    if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "cygwin" ]]; then
        echo "windows_bash"
    elif grep -qi microsoft /proc/version 2>/dev/null; then
        echo "wsl"
    elif [[ "$OSTYPE" == "darwin"* ]]; then
        echo "mac"
    else
        echo "linux"
    fi
}

SHELL_ENV=$(detect_shell_env)
mkdir -p "$HOME/.zikra"

# ── Resolve claude binary — hook shells may not have full PATH ────────────────
CLAUDE_BIN=$(command -v claude 2>/dev/null)
if [ -z "$CLAUDE_BIN" ]; then
  for candidate in \
    "$HOME/.claude/local/claude" \
    "$HOME/.nvm/versions/node/$(node --version 2>/dev/null)/bin/claude" \
    "/usr/local/bin/claude" \
    "/opt/homebrew/bin/claude"; do
    if [ -x "$candidate" ]; then CLAUDE_BIN="$candidate"; break; fi
  done
fi
if [ -z "$CLAUDE_BIN" ]; then
  echo "[zikra_autolog] claude binary not found, skipping diary" >&2
  exit 0
fi

# ── Portable temp dir — /tmp works on WSL/Linux/Mac; fall back to ~/.claude ──
if [[ -d /tmp && -w /tmp ]]; then
    ZIKRA_TMP="/tmp"
else
    ZIKRA_TMP="${HOME}/.claude"
fi
SENTINEL="${ZIKRA_TMP}/.zikra_sentinel"

# ── Portable hostname — hostname -s not available on all Linux distros ────────
HOSTNAME_SHORT="$(hostname -s 2>/dev/null)" \
    || HOSTNAME_SHORT="$(hostname 2>/dev/null | cut -d. -f1)" \
    || HOSTNAME_SHORT="${HOSTNAME:-unknown}"
HOSTNAME_SHORT="${HOSTNAME_SHORT:-unknown}"

# ── Read hook payload from stdin ──────────────────────────────────────────────
PAYLOAD="$(cat 2>/dev/null || echo '{}')"

HOOK_EVENT="$(printf '%s' "$PAYLOAD" | python3 -c \
  "import sys,json; d=json.load(sys.stdin); print(d.get('hook_event_name','Stop'))" \
  2>/dev/null || echo "Stop")"

TRANSCRIPT_PATH="$(printf '%s' "$PAYLOAD" | python3 -c \
  "import sys,json; d=json.load(sys.stdin); print(d.get('transcript_path',''))" \
  2>/dev/null || echo "")"

HOOK_CWD="$(printf '%s' "$PAYLOAD" | python3 -c \
  "import sys,json; d=json.load(sys.stdin); print(d.get('cwd',''))" \
  2>/dev/null || echo "")"

SESSION_ID="$(printf '%s' "$PAYLOAD" | python3 -c \
  "import sys,json; d=json.load(sys.stdin); print(d.get('session_id',''))" \
  2>/dev/null || echo "")"
SID8="${SESSION_ID:0:8}"

# ── Dynamic project detection — CWD overrides install-time DEFAULT_PROJECT ───
detect_project_from_cwd() {
    local cwd="${1:-}"
    local cwd_l host_l
    cwd_l="$(printf '%s' "$cwd" | tr '[:upper:]' '[:lower:]')"
    host_l="$(printf '%s' "$HOSTNAME_SHORT" | tr '[:upper:]' '[:lower:]')"
    if   [[ "$cwd_l" == *"getzikra"* ]] || [[ "$cwd_l" == *"/zikra"* ]]; then echo "zikra"
    elif [[ "$cwd_l" == *"forgenexus"* ]];                                  then echo "forgenexus"
    elif [[ "$cwd_l" == *"veltis"*   ]]; then echo "veltisai"
    elif [[ "$host_l" == *"workstation"* ]] || [[ "$host_l" == *"desktop"* ]]; then echo "$DEFAULT_PROJECT"
    else echo "$DEFAULT_PROJECT"
    fi
}
if [[ -n "$HOOK_CWD" ]]; then
    DEFAULT_PROJECT="$(detect_project_from_cwd "$HOOK_CWD")"
fi

# ── POST helper — logs failures to ~/.zikra/autolog_errors.log ───────────────
LOG_FILE="${HOME}/.zikra/autolog_errors.log"
mkdir -p "$(dirname "$LOG_FILE")"

zikra_post() {
  curl -s -X POST "$ZIKRA_URL" \
    -H "Authorization: Bearer $ZIKRA_TOKEN" \
    -H "Content-Type: application/json" \
    -H "User-Agent: $ZIKRA_USER_AGENT" \
    --connect-timeout 15 \
    --max-time 20 \
    -d "$1" >> "$LOG_FILE" 2>&1 || echo "[$(date)] POST failed" >> "$LOG_FILE"
}

# ── Notify helper — stdout only, works everywhere ────────────────────────────
zikra_notify() {
    echo "[Zikra] $1" >/dev/null 2>&1
}

# ── Clipboard helper — cross-platform ────────────────────────────────────────
copy_to_clipboard() {
    if command -v clip.exe &>/dev/null; then
        echo "$1" | clip.exe
    elif command -v xclip &>/dev/null; then
        echo "$1" | xclip -selection clipboard
    elif command -v xsel &>/dev/null; then
        echo "$1" | xsel --clipboard --input
    elif command -v pbcopy &>/dev/null; then
        echo "$1" | pbcopy
    fi
}

# ── PreCompact handler ────────────────────────────────────────────────────────
if [[ "$HOOK_EVENT" == "PreCompact" ]]; then
  [[ -z "$TRANSCRIPT_PATH" || ! -f "$TRANSCRIPT_PATH" ]] && exit 0

  (
    SUMMARY="$(tail -100 "$TRANSCRIPT_PATH" 2>/dev/null | "$CLAUDE_BIN" -p \
      'Extract key decisions, problems solved, and what was being worked on from this conversation transcript. Be factual and concise — max 200 words. Plain text only, no markdown.' \
      2>/dev/null || echo "Pre-compact summary unavailable.")"

    TITLE="auto-compact:$(date +%Y-%m-%d-%H%M):${HOSTNAME_SHORT}"

    BODY="$(python3 -c "
import json, sys
title   = sys.argv[1]
summary = sys.argv[2]
project = sys.argv[3]
host    = sys.argv[4]
print(json.dumps({
    'command':     'save_memory',
    'project':     project,
    'memory_type': 'conversation',
    'title':       title,
    'content_md':  summary,
    'tags':        None,
    'created_by':  host,
}))" "$TITLE" "$SUMMARY" "$DEFAULT_PROJECT" "$HOSTNAME_SHORT" 2>/dev/null)"

    [[ -n "$BODY" ]] && zikra_post "$BODY"
  ) >> "$HOME/.zikra/hook_errors.log" 2>&1 &
  disown
  exit 0
fi

# ── Stop handler (default for all other events) ───────────────────────────────

# Touch transcript to wake zikra_watcher.py (if running)
if [[ -n "$TRANSCRIPT_PATH" && -f "$TRANSCRIPT_PATH" ]]; then
  touch "$TRANSCRIPT_PATH" 2>/dev/null || true
fi

# ── Portable lock: fail-fast if another Stop hook is already running ──────────
LOCKFILE="${ZIKRA_TMP}/.zikra_diary.lock"
if command -v flock >/dev/null 2>&1; then
  # Linux / WSL: flock is atomic and fd-based
  exec 9>"$LOCKFILE"
  flock -n 9 || exit 0
else
  # macOS fallback: mkdir is atomic
  if ! mkdir "${LOCKFILE}.d" 2>/dev/null; then
    # Release stale lock if older than 5 minutes
    if [[ -d "${LOCKFILE}.d" ]]; then
      LOCK_AGE=$(( $(date +%s) - $(stat -f %m "${LOCKFILE}.d" 2>/dev/null || echo 0) ))
      if [[ $LOCK_AGE -gt 300 ]]; then
        rm -rf "${LOCKFILE}.d" && mkdir "${LOCKFILE}.d" 2>/dev/null || exit 0
      else
        exit 0
      fi
    else
      exit 0
    fi
  fi
  trap 'rm -rf "${LOCKFILE}.d"' EXIT
fi

# ── Sentinel cooldown: throttle PER SESSION so rapid Stops in one session
# don't hammer claude -p, while concurrent sessions never block each other.
# (The old global 120s sentinel silently dropped closely-spaced sessions.)
[[ -n "$SID8" ]] && SENTINEL="${SENTINEL}_${SID8}"
NOW="$(date +%s)"
if [[ -f "$SENTINEL" ]]; then
  LAST="$(cat "$SENTINEL" 2>/dev/null || echo 0)"
  DIFF=$(( NOW - LAST ))
  if [[ $DIFF -lt 120 ]]; then
    # Release lock before early exit
    if command -v flock >/dev/null 2>&1; then
      exec 9>&-
    else
      rm -rf "${LOCKFILE}.d" 2>/dev/null
      trap - EXIT
    fi
    exit 0
  fi
fi
echo "$NOW" > "$SENTINEL"
# Prune per-session sentinels older than a day
find "$ZIKRA_TMP" -maxdepth 1 -name '.zikra_sentinel*' -mmin +1440 -delete 2>/dev/null || true

# ── Portable timeout — GNU coreutils on Linux/WSL, gtimeout on macOS ─────────
_TIMEOUT_CMD=""
if command -v timeout >/dev/null 2>&1; then
  _TIMEOUT_CMD="timeout 120"
elif command -v gtimeout >/dev/null 2>&1; then
  _TIMEOUT_CMD="gtimeout 120"
fi

(
  # The payload names THIS session's transcript — use it. Globbing for the
  # newest transcript across all projects grabs the wrong session on a busy
  # machine, so it is only a fallback for ancient Claude Code versions.
  LATEST=""
  if [[ -n "$TRANSCRIPT_PATH" && -f "$TRANSCRIPT_PATH" ]]; then
    LATEST="$TRANSCRIPT_PATH"
  elif command -v find >/dev/null 2>&1; then
    LATEST="$(find "$HOME/.claude/projects" -maxdepth 3 -name '*.jsonl' \
      2>/dev/null | xargs ls -t 2>/dev/null | head -1)"
  fi

  [[ -z "$LATEST" || ! -f "$LATEST" ]] && exit 0

  # Adaptive transcript length with 200KB byte cap
  LINE_COUNT="$(wc -l < "$LATEST" 2>/dev/null || echo 0)"
  TAIL_LINES=200
  [[ "$LINE_COUNT" -lt 200 ]] && TAIL_LINES="$LINE_COUNT"
  [[ "$TAIL_LINES" -lt 80 ]] && TAIL_LINES=80

  # ── Server-side distillation (v1.1) ─────────────────────────────────────
  # Upload the transcript tail; the server distills it into a diary plus
  # typed memories (decision/bug/reference). Only when the server has no
  # distiller LLM configured do we fall back to the local claude -p diary.
  DISTILLED=0
  INGEST_TMP="$(mktemp "${ZIKRA_TMP}/.zikra_ingest.XXXXXX" 2>/dev/null)"
  if [[ -n "$INGEST_TMP" ]]; then
    tail -"$TAIL_LINES" "$LATEST" 2>/dev/null | head -c 200000 | python3 -c "
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
      INGEST_RESP="$(curl -s -X POST "$ZIKRA_URL" \
        -H "Authorization: Bearer $ZIKRA_TOKEN" \
        -H "Content-Type: application/json" \
        -H "User-Agent: $ZIKRA_USER_AGENT" \
        --connect-timeout 15 --max-time 30 \
        --data-binary @"$INGEST_TMP" 2>/dev/null)"
      [[ "$INGEST_RESP" == *'"queued"'* ]] && DISTILLED=1
    fi
    rm -f "$INGEST_TMP"
  fi

  DIARY=""
  if [[ "$DISTILLED" -eq 0 ]]; then
  DIARY="$(tail -"$TAIL_LINES" "$LATEST" 2>/dev/null \
    | head -c 200000 \
    | $_TIMEOUT_CMD "$CLAUDE_BIN" -p \
      'From this Claude Code session transcript, write a complete diary entry. Include:
1. What was built, fixed, or deployed (with file names and specifics)
2. Key decisions made and WHY
3. Problems encountered and how they were resolved
4. Current state — what works now, what is left
Be thorough — this is the only record of this session. 300-500 words. Factual, first-person, present tense.' \
      2>/dev/null || echo "Session diary generation failed.")"

  # Stable per-session title: later Stops in the same session UPDATE the one
  # diary memory (save_memory upserts on title+type+project) instead of
  # piling up a new conversation memory per turn.
  if [[ -n "$SID8" ]]; then
    TITLE="diary:$(date +%Y-%m-%d):${SID8}:${HOSTNAME_SHORT}"
  else
    TITLE="diary:$(date +%Y-%m-%d-%H%M):${HOSTNAME_SHORT}"
  fi

  BODY="$(python3 -c "
import json, sys
title   = sys.argv[1]
diary   = sys.argv[2]
project = sys.argv[3]
host    = sys.argv[4]
print(json.dumps({
    'command':     'save_memory',
    'project':     project,
    'memory_type': 'conversation',
    'title':       title,
    'content_md':  diary,
    'tags':        None,
    'created_by':  host,
}))" "$TITLE" "$DIARY" "$DEFAULT_PROJECT" "$HOSTNAME_SHORT" 2>/dev/null)"

  [[ -n "$BODY" ]] && zikra_post "$BODY"
  fi  # DISTILLED -eq 0 — local diary fallback ends here

  # ── Log run for every session ────────────────────────────────────────
  # v1.0.6: prompt_id linkage is now handled server-side via the pending_runs
  # table — cmd_get_prompt records (runner, prompt_id); cmd_log_run from the
  # same runner consumes it. No /tmp rendezvous file anymore.
  read T_IN T_OUT T_CR T_CC <<< $(python3 -c "
import json, sys
ti, to, cr, cc = 0, 0, 0, 0
for line in open(sys.argv[1]):
    try:
        u = json.loads(line).get('message', {}).get('usage', {})
        ti += u.get('input_tokens', 0)
        to += u.get('output_tokens', 0)
        cr += u.get('cache_read_input_tokens', 0)
        cc += u.get('cache_creation_input_tokens', 0)
    except: pass
print(ti, to, cr, cc)
" "$LATEST" 2>/dev/null)
  T_IN=${T_IN:-0}; T_OUT=${T_OUT:-0}; T_CR=${T_CR:-0}; T_CC=${T_CC:-0}

  # v1.0.7: push the generated diary into output_summary so the run row itself
  # carries the narrative. Previously we only wrote the diary as a floating
  # memory with no prompt_id/run_id linkage, so clicking a run in the Zikra UI
  # showed "auto-logged by zikra_autolog.sh" instead of the real story.
  SUMMARY_TEXT="$DIARY"
  if [[ "$DISTILLED" -eq 1 ]]; then
    # Server will upsert the distilled diary into this run row (longer
    # summary wins), so a short placeholder is fine here.
    SUMMARY_TEXT="session queued for server-side distillation"
  fi
  [[ -z "$SUMMARY_TEXT" || "$SUMMARY_TEXT" == "Session diary generation failed." ]] \
      && SUMMARY_TEXT="auto-logged by zikra_autolog.sh (diary unavailable)"

  # session_id makes the server upsert one run row per session — the watcher
  # daemon and repeated Stop events merge instead of double-logging.
  RUN_BODY="$(python3 -c "
import json, sys
body = {
  'command':               'log_run',
  'project':               sys.argv[1],
  'runner':                sys.argv[2],
  'status':                'success',
  'output_summary':        sys.argv[3],
  'tokens_input':          int(sys.argv[4]),
  'tokens_output':         int(sys.argv[5]),
  'tokens_cache_read':     int(sys.argv[6]),
  'tokens_cache_creation': int(sys.argv[7]),
}
if sys.argv[8]:
    body['session_id'] = sys.argv[8]
print(json.dumps(body))" \
    "$DEFAULT_PROJECT" "$HOSTNAME_SHORT" "$SUMMARY_TEXT" \
    "$T_IN" "$T_OUT" "$T_CR" "$T_CC" "$SESSION_ID" 2>/dev/null)"

  [[ -n "$RUN_BODY" ]] && zikra_post "$RUN_BODY"
  # ──────────────────────────────────────────────────────────────────────

  zikra_notify "Session logged"
) >> "$HOME/.zikra/hook_errors.log" 2>&1 &
disown

# ── cross-platform notification ──────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$SCRIPT_DIR/notify.sh" ]; then
    bash "$SCRIPT_DIR/notify.sh" "Session logged to Zikra" "Zikra" 2>/dev/null &
fi

exit 0
