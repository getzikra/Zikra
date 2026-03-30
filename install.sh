#!/usr/bin/env bash
# Zikra Installer v1.0
# Usage: curl -fsSL https://zikra.dev/install.sh | bash -s -- [--minimal|--standard|--full]

set -euo pipefail

PROFILE="${1:---standard}"
ZIKRA_RAW="https://raw.githubusercontent.com/getzikra/zikra/main"

# ── Validate profile ────────────────────────────────────────────────────────
case "$PROFILE" in
  --minimal|--standard|--full) ;;
  *)
    echo "Unknown profile: $PROFILE"
    echo "Usage: $0 [--minimal|--standard|--full]"
    exit 1
    ;;
esac

PROFILE_NAME="${PROFILE#--}"

# ── Detect OS ───────────────────────────────────────────────────────────────
OS="$(uname -s)"

# ── Banner ──────────────────────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════════════╗"
printf  "║   Zikra Installer v1.0 — profile: %-12s  ║\n" "$PROFILE_NAME"
echo "╚══════════════════════════════════════════════════╝"
echo ""

# ── Input validation helpers ────────────────────────────────────────────────

prompt_url() {
  while true; do
    read -rp "Zikra webhook URL (e.g. https://n8n.yourdomain.com/webhook/zikra): " ZIKRA_URL
    if [[ "$ZIKRA_URL" =~ ^https?:// ]]; then
      break
    else
      echo "  ✗ URL must start with http:// or https://"
    fi
  done
}

prompt_token() {
  while true; do
    read -rp "Bearer token (e.g. velt-xxxxxxxx): " ZIKRA_TOKEN
    if [[ -n "$ZIKRA_TOKEN" ]]; then
      break
    else
      echo "  ✗ Token cannot be empty"
    fi
  done
}

prompt_project() {
  while true; do
    read -rp "Default project name (lowercase, no spaces): " DEFAULT_PROJECT
    if [[ "$DEFAULT_PROJECT" =~ ^[a-z0-9][a-z0-9_-]*$ ]]; then
      break
    else
      echo "  ✗ Must be lowercase letters, digits, hyphens, or underscores only"
    fi
  done
}

# ── Ask the 3 questions ─────────────────────────────────────────────────────
prompt_url
prompt_token
prompt_project

echo ""
echo "Installing Zikra ($PROFILE_NAME)..."
echo ""

# ── Patch helper ────────────────────────────────────────────────────────────
patch_file() {
  local f="$1"
  if [[ "$OS" == "Darwin" ]]; then
    sed -i '' "s|ZIKRA_URL_PLACEHOLDER|${ZIKRA_URL}|g"            "$f"
    sed -i '' "s|ZIKRA_TOKEN_PLACEHOLDER|${ZIKRA_TOKEN}|g"         "$f"
    sed -i '' "s|DEFAULT_PROJECT_PLACEHOLDER|${DEFAULT_PROJECT}|g" "$f"
  else
    sed -i  "s|ZIKRA_URL_PLACEHOLDER|${ZIKRA_URL}|g"            "$f"
    sed -i  "s|ZIKRA_TOKEN_PLACEHOLDER|${ZIKRA_TOKEN}|g"         "$f"
    sed -i  "s|DEFAULT_PROJECT_PLACEHOLDER|${DEFAULT_PROJECT}|g" "$f"
  fi
}

# ── Always install (all profiles) ───────────────────────────────────────────

mkdir -p ~/.claude/hooks ~/.claude/cache

echo "  → Downloading zikra_autolog.sh..."
curl -fsSL "$ZIKRA_RAW/hooks/zikra_autolog.sh" -o ~/.claude/zikra_autolog.sh
chmod +x ~/.claude/zikra_autolog.sh
patch_file ~/.claude/zikra_autolog.sh
echo "  ✓ zikra_autolog.sh installed"

if [[ ! -f ~/.claude/CLAUDE.md ]]; then
  echo "  → Downloading CLAUDE.md..."
  curl -fsSL "$ZIKRA_RAW/context/CLAUDE.md" -o ~/.claude/CLAUDE.md
  patch_file ~/.claude/CLAUDE.md
  echo "  ✓ CLAUDE.md installed"
else
  echo "  ~ CLAUDE.md already exists — skipping (edit manually to update credentials)"
fi

# Wire Stop hook in settings.json
python3 - <<'PYEOF'
import json, os, sys

settings_path = os.path.expanduser("~/.claude/settings.json")
autolog       = os.path.expanduser("~/.claude/zikra_autolog.sh")

if os.path.exists(settings_path):
    with open(settings_path) as f:
        try:
            s = json.load(f)
        except json.JSONDecodeError:
            s = {}
else:
    s = {}

s.setdefault("hooks", {})
s["hooks"].setdefault("Stop", [])

stop_hook = {
    "matcher": "",
    "hooks": [{"type": "command", "command": autolog}]
}

already_wired = any(
    any(h.get("command") == autolog for h in entry.get("hooks", []))
    for entry in s["hooks"]["Stop"]
)

if not already_wired:
    s["hooks"]["Stop"].append(stop_hook)
    with open(settings_path, "w") as f:
        json.dump(s, f, indent=2)
    print("  ✓ Stop hook wired in settings.json")
else:
    print("  ~ Stop hook already present in settings.json")
PYEOF

# ── Standard + Full: PreCompact hook ────────────────────────────────────────

if [[ "$PROFILE_NAME" == "standard" || "$PROFILE_NAME" == "full" ]]; then
  python3 - <<'PYEOF'
import json, os

settings_path = os.path.expanduser("~/.claude/settings.json")
autolog       = os.path.expanduser("~/.claude/zikra_autolog.sh")

with open(settings_path) as f:
    s = json.load(f)

s["hooks"].setdefault("PreCompact", [])

precompact_hook = {
    "matcher": "auto",
    "hooks": [{"type": "command", "command": autolog}]
}

already_wired = any(
    any(h.get("command") == autolog for h in entry.get("hooks", []))
    for entry in s["hooks"]["PreCompact"]
)

if not already_wired:
    s["hooks"]["PreCompact"].append(precompact_hook)
    with open(settings_path, "w") as f:
        json.dump(s, f, indent=2)
    print("  ✓ PreCompact hook wired in settings.json")
else:
    print("  ~ PreCompact hook already present in settings.json")
PYEOF
fi

# ── Full only ────────────────────────────────────────────────────────────────

if [[ "$PROFILE_NAME" == "full" ]]; then
  echo "  → Downloading zikra_watcher.py..."
  curl -fsSL "$ZIKRA_RAW/daemon/zikra_watcher.py" -o ~/.claude/zikra_watcher.py
  chmod +x ~/.claude/zikra_watcher.py
  patch_file ~/.claude/zikra_watcher.py
  echo "  ✓ zikra_watcher.py installed"

  echo "  → Downloading zikra-statusline.js..."
  curl -fsSL "$ZIKRA_RAW/hooks/zikra-statusline.js" -o ~/.claude/hooks/zikra-statusline.js
  chmod +x ~/.claude/hooks/zikra-statusline.js
  echo "  ✓ zikra-statusline.js installed"

  # Seed stats cache
  cat > ~/.claude/cache/zikra-stats.json <<'JSON'
{"runs_today":0,"runs_total":0,"memory_count":0}
JSON
  echo "  ✓ zikra-stats.json seeded"

  # Wire statusLine in settings.json
  python3 - <<'PYEOF'
import json, os

settings_path   = os.path.expanduser("~/.claude/settings.json")
statusline_path = os.path.expanduser("~/.claude/hooks/zikra-statusline.js")

with open(settings_path) as f:
    s = json.load(f)

s["statusLine"] = {"type": "command", "command": statusline_path}

with open(settings_path, "w") as f:
    json.dump(s, f, indent=2)

print("  ✓ statusLine wired in settings.json")
PYEOF

  # Install systemd service on Linux
  if [[ "$OS" == "Linux" ]]; then
    PYTHON_BIN="$(which python3)"
    SERVICE_DIR="$HOME/.config/systemd/user"
    SERVICE_FILE="$SERVICE_DIR/zikra-watcher.service"
    mkdir -p "$SERVICE_DIR"
    cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=Zikra Session Watcher Daemon
After=network.target

[Service]
ExecStart=$PYTHON_BIN $HOME/.claude/zikra_watcher.py
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
EOF
    systemctl --user daemon-reload  2>/dev/null || true
    systemctl --user enable zikra-watcher 2>/dev/null || true
    systemctl --user start  zikra-watcher 2>/dev/null || true
    echo "  ✓ systemd user service installed (zikra-watcher)"
  else
    echo "  ~ macOS detected: systemd skipped."
    echo "    To auto-start the watcher, add a launchd plist for:"
    echo "    python3 ~/.claude/zikra_watcher.py"
  fi
fi

# ── Verify webhook ───────────────────────────────────────────────────────────

echo ""
echo "Verifying webhook..."

HTTP_STATUS="$(curl -s -o /dev/null -w "%{http_code}" \
  -X POST "$ZIKRA_URL" \
  -H "Authorization: Bearer $ZIKRA_TOKEN" \
  -H "Content-Type: application/json" \
  -H "User-Agent: curl/7.81.0" \
  -d "{\"command\":\"search\",\"query\":\"install-test\",\"project\":\"${DEFAULT_PROJECT}\",\"max_results\":1}" \
  --connect-timeout 10 \
  2>/dev/null || echo "000")"

if [[ "$HTTP_STATUS" == "200" ]]; then
  echo "  ✓ Webhook reachable (HTTP 200)"
else
  echo "  ✗ Webhook returned HTTP $HTTP_STATUS — check your URL and token"
fi

# ── Print summary ────────────────────────────────────────────────────────────

echo ""
echo "Installed files:"
[[ -f ~/.claude/zikra_autolog.sh ]]          && echo "  ~/.claude/zikra_autolog.sh"
[[ -f ~/.claude/CLAUDE.md ]]                  && echo "  ~/.claude/CLAUDE.md"
[[ -f ~/.claude/settings.json ]]              && echo "  ~/.claude/settings.json  (hooks wired)"
[[ -f ~/.claude/zikra_watcher.py ]]           && echo "  ~/.claude/zikra_watcher.py"
[[ -f ~/.claude/hooks/zikra-statusline.js ]]  && echo "  ~/.claude/hooks/zikra-statusline.js"
[[ -f ~/.claude/cache/zikra-stats.json ]]     && echo "  ~/.claude/cache/zikra-stats.json"

echo ""
echo "✓ Zikra installed (${PROFILE_NAME}). Restart Claude Code to activate."
echo ""
