# g:update_zikra
# Run when you want to pull the latest hooks and config

You are updating Zikra on this machine.

## Step 1 — Pull latest hooks from GitHub

curl -fsSL https://raw.githubusercontent.com/getzikra/zikra/main/hooks/zikra_autolog.sh \
  -o ~/.claude/zikra_autolog.sh
chmod +x ~/.claude/zikra_autolog.sh
echo "Hook updated"

## Step 2 — Pull latest CLAUDE.md

curl -fsSL https://raw.githubusercontent.com/getzikra/zikra/main/context/CLAUDE.md \
  -o ~/.claude/CLAUDE.md
echo "CLAUDE.md updated"

## Step 3 — If Lite is installed, upgrade it

if command -v zikra &>/dev/null; then
  pip install zikra-lite --upgrade --break-system-packages
  echo "Zikra Lite upgraded to latest"
fi

## Step 4 — Test connection (same as sync)

Read token and URL from ~/.claude/settings.json
Run test search curl
Report success or failure

## Step 5 — Report to user

Print exactly what was updated and the current version.
