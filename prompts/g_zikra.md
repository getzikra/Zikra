# g_zikra

Install or update Zikra persistent memory on this machine.
Works for both Zikra Lite (localhost) and Zikra Full (n8n server).
Follow every step in order. Run all bash commands exactly as shown.
Proceed without asking for confirmation between steps.

---

## Step 1 — Check if already installed

```bash
cat ~/.zikra/token 2>/dev/null
```

Parse the output. If `ZIKRA_URL`, `ZIKRA_TOKEN`, and `ZIKRA_PROJECT` are all present and non-empty:
- Source the file: `source ~/.zikra/token`
- Set `MY_TOKEN="$ZIKRA_TOKEN"`
- Skip to **Step 5** (update hooks only — do not re-create token, do not overwrite CLAUDE.md)

Otherwise continue to Step 2.

---

## Step 2 — Ask 4 questions

Ask these four questions one at a time. Wait for each answer.

**Q1 — Zikra URL**
Where is your Zikra server running?
- Zikra (local): `http://localhost:8000`
- Zikra Full (remote): `https://n8n.yourserver.com/webhook/zikra`

**Q2 — Admin token**
The token from your server admin, or the value of `ZIKRA_TOKEN` in `.env` on the server.
This is used once to create your machine token.

**Q3 — Your name**
First name or handle (lowercase, no spaces, e.g. `mukarram`).

**Q4 — Default project**
Leave blank to use `global`. Otherwise a lowercase project name (e.g. `backend`, `mobile`).

Store answers:
```
ZIKRA_URL=<Q1>
ADMIN_TOKEN=<Q2>
ZIKRA_PERSON=<Q3, lowercased>
ZIKRA_PROJECT=<Q4 or "global">
ZIKRA_MACHINE=$(hostname)
```

---

## Step 3 — Create a token for this user+machine

Use the admin token to register a developer token for this machine:

```bash
RESPONSE=$(curl -s -X POST "$ZIKRA_URL" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -H "User-Agent: curl/7.81.0" \
  -d "{
    \"command\":      \"create_token\",
    \"person_name\":  \"$ZIKRA_PERSON\",
    \"token_name\":   \"${ZIKRA_PERSON}-${ZIKRA_MACHINE}\",
    \"role\":         \"developer\",
    \"project\":      \"$ZIKRA_PROJECT\"
  }")
echo "$RESPONSE"
```

Parse the response:
- Contains `"token"` field → extract value as `MY_TOKEN`
- Contains `"already exists"` → ask: *"A token for this machine already exists. Paste your existing token:"* → store answer as `MY_TOKEN`
- Contains `401` or `Unauthorized` → admin token is wrong, return to Step 2 Q2

---

## Step 4 — Save credentials

```bash
mkdir -p ~/.zikra
cat > ~/.zikra/token <<EOF
ZIKRA_URL=$ZIKRA_URL
ZIKRA_TOKEN=$MY_TOKEN
ZIKRA_PROJECT=$ZIKRA_PROJECT
ZIKRA_PERSON=$ZIKRA_PERSON
ZIKRA_MACHINE=$ZIKRA_MACHINE
EOF
chmod 600 ~/.zikra/token
```

Confirm by printing: `cat ~/.zikra/token`

---

## Step 5 — Install/update hooks

Determine which raw GitHub URL to use:

```bash
if [[ "$ZIKRA_URL" == *"localhost"* || "$ZIKRA_URL" == *"127.0.0.1"* ]]; then
  ZIKRA_RAW="https://raw.githubusercontent.com/getzikra/zikra-lite/main"
else
  ZIKRA_RAW="https://raw.githubusercontent.com/getzikra/zikra/main"
fi
```

Download and install the autolog hook:

```bash
mkdir -p ~/.claude
curl -fsSL "$ZIKRA_RAW/hooks/zikra_autolog.sh" -o ~/.claude/zikra_autolog.sh
chmod +x ~/.claude/zikra_autolog.sh
```

Replace all four placeholders (macOS uses `sed -i ''`, Linux/WSL uses `sed -i`):

```bash
OS="$(uname -s)"
SED_I() { [[ "$OS" == "Darwin" ]] && sed -i '' "$@" || sed -i "$@"; }

SED_I "s|ZIKRA_URL_PLACEHOLDER|${ZIKRA_URL}|g"                          ~/.claude/zikra_autolog.sh
SED_I "s|ZIKRA_TOKEN_PLACEHOLDER|${MY_TOKEN}|g"                         ~/.claude/zikra_autolog.sh
SED_I "s|DEFAULT_PROJECT_PLACEHOLDER|${ZIKRA_PROJECT}|g"                ~/.claude/zikra_autolog.sh
```

Verify no placeholders remain:

```bash
grep "PLACEHOLDER" ~/.claude/zikra_autolog.sh \
  && echo "WARNING: placeholders remain — check sed output above" \
  || echo "✓ zikra_autolog.sh patched"
```

---

## Step 6 — Install CLAUDE.md (only if not already present)

```bash
OS="$(uname -s)"
SED_I() { [[ "$OS" == "Darwin" ]] && sed -i '' "$@" || sed -i "$@"; }

_patch_zikra_claudemd() {
  SED_I "s|ZIKRA_URL_PLACEHOLDER|${ZIKRA_URL}|g"           "$1"
  SED_I "s|ZIKRA_TOKEN_PLACEHOLDER|${MY_TOKEN}|g"          "$1"
  SED_I "s|DEFAULT_PROJECT_PLACEHOLDER|${ZIKRA_PROJECT}|g" "$1"
  SED_I "s|RUNNER_PLACEHOLDER|${ZIKRA_PERSON}@${ZIKRA_MACHINE}|g" "$1"
}

if [ ! -f ~/.claude/CLAUDE.md ]; then
  curl -fsSL "$ZIKRA_RAW/context/CLAUDE.md" -o ~/.claude/CLAUDE.md
  _patch_zikra_claudemd ~/.claude/CLAUDE.md
  echo "✓ CLAUDE.md installed"
elif grep -q "Zikra" ~/.claude/CLAUDE.md 2>/dev/null; then
  echo "~ CLAUDE.md already contains Zikra section — skipping"
else
  echo "CLAUDE.md already exists. Appending Zikra section."
  _TMP_ZIKRA="$(mktemp)"
  curl -fsSL "$ZIKRA_RAW/context/CLAUDE.md" -o "$_TMP_ZIKRA"
  _patch_zikra_claudemd "$_TMP_ZIKRA"
  printf '\n\n---\n## Zikra Memory System\n\n' >> ~/.claude/CLAUDE.md
  cat "$_TMP_ZIKRA" >> ~/.claude/CLAUDE.md
  rm -f "$_TMP_ZIKRA"
  echo "✓ Zikra section appended to existing CLAUDE.md"
fi
```

---

## Step 7 — Wire hooks into settings.json

Run the following Python inline. It adds Stop and PreCompact hooks without duplicating them if already present:

```bash
python3 - <<'PYEOF'
import json, os

settings_path = os.path.expanduser("~/.claude/settings.json")
autolog       = os.path.expanduser("~/.claude/zikra_autolog.sh")

s = {}
if os.path.exists(settings_path):
    with open(settings_path) as f:
        try:
            s = json.load(f)
        except json.JSONDecodeError:
            s = {}

s.setdefault("hooks", {})

# Stop hook
s["hooks"].setdefault("Stop", [])
stop_present = any(
    any(h.get("command") == autolog for h in e.get("hooks", []))
    for e in s["hooks"]["Stop"]
)
if not stop_present:
    s["hooks"]["Stop"].append({
        "matcher": "",
        "hooks": [{"type": "command", "command": autolog}]
    })
    print("✓ Stop hook wired")
else:
    print("~ Stop hook already present")

# PreCompact hook
s["hooks"].setdefault("PreCompact", [])
precompact_present = any(
    any(h.get("command") == autolog for h in e.get("hooks", []))
    for e in s["hooks"]["PreCompact"]
)
if not precompact_present:
    s["hooks"]["PreCompact"].append({
        "matcher": "auto",
        "hooks": [{"type": "command", "command": autolog}]
    })
    print("✓ PreCompact hook wired")
else:
    print("~ PreCompact hook already present")

with open(settings_path, "w") as f:
    json.dump(s, f, indent=2)
PYEOF
```

---

## Step 8 — Register this machine (new installs only)

Skip this step if you came from Step 1 (already installed).

```bash
curl -s -X POST "$ZIKRA_URL" \
  -H "Authorization: Bearer $MY_TOKEN" \
  -H "Content-Type: application/json" \
  -H "User-Agent: curl/7.81.0" \
  -d "{
    \"command\":     \"save_memory\",
    \"project\":     \"$ZIKRA_PROJECT\",
    \"memory_type\": \"decision\",
    \"title\":       \"machine onboarded: ${ZIKRA_MACHINE} (${ZIKRA_PERSON})\",
    \"content_md\":  \"Zikra installed on ${ZIKRA_MACHINE} for ${ZIKRA_PERSON}. URL: ${ZIKRA_URL}. Project: ${ZIKRA_PROJECT}.\",
    \"tags\":        null,
    \"created_by\":  \"${ZIKRA_PERSON}@${ZIKRA_MACHINE}\"
  }" > /dev/null && echo "✓ Machine registered"
```

---

## Step 9 — Test the connection

```bash
SEARCH_RESP=$(curl -s -X POST "$ZIKRA_URL" \
  -H "Authorization: Bearer $MY_TOKEN" \
  -H "Content-Type: application/json" \
  -H "User-Agent: curl/7.81.0" \
  -d "{\"command\":\"search\",\"query\":\"zikra\",\"project\":\"$ZIKRA_PROJECT\",\"limit\":1}")

echo "$SEARCH_RESP"
```

- Response contains `"results"` array → **SUCCESS** — continue to Step 10
- Response contains `"error"` or no JSON → **FAIL** — print the full response, stop here, and tell the user what went wrong

---

## Step 10 — Print summary

Print this block with real values substituted:

```
─────────────────────────────────────────────────
  Zikra connected ✓
─────────────────────────────────────────────────
  Machine : <ZIKRA_MACHINE>
  User    : <ZIKRA_PERSON>
  URL     : <ZIKRA_URL>
  Token   : <first 8 chars of MY_TOKEN>...
  Project : <ZIKRA_PROJECT>
  Status  : Zikra connected   ← new install
            Zikra updated     ← hooks refreshed
─────────────────────────────────────────────────
  Next: Start a new Claude Code session.
        Memory is active from the first message.
─────────────────────────────────────────────────
```

---

## Step 11 — Install statusline (Zikra bar)

```bash
mkdir -p ~/.claude/hooks ~/.claude/cache

# Download statusline script
curl -fsSL $ZIKRA_RAW/hooks/zikra-statusline.js \
  -o ~/.claude/hooks/zikra-statusline.js
chmod +x ~/.claude/hooks/zikra-statusline.js

# Patch placeholders
if [ "$OS" = "Darwin" ]; then
  sed -i '' "s|ZIKRA_URL_PLACEHOLDER|$ZIKRA_URL|g" ~/.claude/hooks/zikra-statusline.js
  sed -i '' "s|ZIKRA_TOKEN_PLACEHOLDER|$MY_TOKEN|g" ~/.claude/hooks/zikra-statusline.js
  sed -i '' "s|DEFAULT_PROJECT_PLACEHOLDER|$ZIKRA_PROJECT|g" ~/.claude/hooks/zikra-statusline.js
else
  sed -i "s|ZIKRA_URL_PLACEHOLDER|$ZIKRA_URL|g" ~/.claude/hooks/zikra-statusline.js
  sed -i "s|ZIKRA_TOKEN_PLACEHOLDER|$MY_TOKEN|g" ~/.claude/hooks/zikra-statusline.js
  sed -i "s|DEFAULT_PROJECT_PLACEHOLDER|$ZIKRA_PROJECT|g" ~/.claude/hooks/zikra-statusline.js
fi

# Seed the stats cache
echo '{"runs_today":0,"runs_total":0,"memory_count":0,"last_saved":null,"project":"'$ZIKRA_PROJECT'"}' \
  > ~/.claude/cache/zikra-stats.json

# Download and install stats update hook
curl -fsSL $ZIKRA_RAW/hooks/zikra-stats-update.sh \
  -o ~/.claude/hooks/zikra-stats-update.sh
chmod +x ~/.claude/hooks/zikra-stats-update.sh
```

Wire statusLine and stats update hook in settings.json using python3:
```python
import json, os
path = os.path.expanduser('~/.claude/settings.json')
s = json.load(open(path)) if os.path.exists(path) else {}

# Wire statusline
hook_cmd = 'node ~/.claude/hooks/zikra-statusline.js'
if s.get('statusLine', {}).get('command') != hook_cmd:
    s['statusLine'] = {'type': 'command', 'command': hook_cmd}
    print('Statusline wired')
else:
    print('Statusline already wired')

# Wire stats update hook to Stop
home = os.path.expanduser('~')
stats_cmd = f'bash {home}/.claude/hooks/zikra-stats-update.sh'
stop_hooks = s.setdefault('hooks', {}).setdefault('Stop', [])
if not any(stats_cmd in str(h) for h in stop_hooks):
    stop_hooks.append({'hooks': [{'type': 'command', 'command': stats_cmd, 'timeout': 10}]})
    print('Stats update hook wired to Stop')
else:
    print('Stats update hook already wired')

json.dump(s, open(path, 'w'), indent=2)
```

Print: Zikra bar installed. Restart Claude Code to see it.
