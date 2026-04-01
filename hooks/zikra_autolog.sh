#!/usr/bin/env bash
# zikra_autolog.sh v8
# Claude Code hook handler for Stop and PreCompact events.
# Saves session diary and pre-compact summaries to Zikra persistent memory.
#
# Invoked automatically by Claude Code hooks — never run manually.
# Works on: WSL, native Linux, macOS, Git Bash / MSYS on Windows.

ZIKRA_URL="ZIKRA_URL_PLACEHOLDER"
ZIKRA_TOKEN="ZIKRA_TOKEN_PLACEHOLDER"
DEFAULT_PROJECT="DEFAULT_PROJECT_PLACEHOLDER"

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

# ── POST helper — completely silent ──────────────────────────────────────────
zikra_post() {
  curl -s -X POST "$ZIKRA_URL" \
    -H "Authorization: Bearer $ZIKRA_TOKEN" \
    -H "Content-Type: application/json" \
    -H "User-Agent: curl/7.81.0" \
    --connect-timeout 15 \
    -d "$1" > /dev/null 2>&1
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
    SUMMARY="$(tail -100 "$TRANSCRIPT_PATH" 2>/dev/null | claude -p \
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
  ) &
  disown
  exit 0
fi

# ── Stop handler (default for all other events) ───────────────────────────────

# Touch transcript to wake zikra_watcher.py (if running)
if [[ -n "$TRANSCRIPT_PATH" && -f "$TRANSCRIPT_PATH" ]]; then
  touch "$TRANSCRIPT_PATH" 2>/dev/null || true
fi

(
  # Sentinel: skip if a diary was already saved in the last 60 seconds
  NOW="$(date +%s)"
  if [[ -f "$SENTINEL" ]]; then
    LAST="$(cat "$SENTINEL" 2>/dev/null || echo 0)"
    DIFF=$(( NOW - LAST ))
    if [[ $DIFF -lt 60 ]]; then
      exit 0
    fi
  fi
  echo "$NOW" > "$SENTINEL"

  # Find the most recently modified transcript
  LATEST=""
  if command -v find >/dev/null 2>&1; then
    LATEST="$(find "$HOME/.claude/projects" -name '*.jsonl' 2>/dev/null \
      | xargs ls -t 2>/dev/null | head -1 || true)"
  fi

  [[ -z "$LATEST" || ! -f "$LATEST" ]] && exit 0

  DIARY="$(tail -80 "$LATEST" 2>/dev/null | claude -p \
    'From this Claude Code session transcript, write a concise diary entry covering: what was built or fixed, key decisions made and WHY, problems solved, and any failures or blockers encountered. Max 250 words. Factual, first-person, present tense.' \
    2>/dev/null || echo "Session diary generation failed.")"

  TITLE="diary:$(date +%Y-%m-%d):${HOSTNAME_SHORT}"

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
  zikra_notify "Session logged"
) &
disown

# ── cross-platform notification ──────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
bash "$SCRIPT_DIR/notify.sh" "Session logged to Zikra" "Zikra" 2>/dev/null &

exit 0
