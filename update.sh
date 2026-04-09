#!/usr/bin/env bash
# update.sh — Safe Zikra server update
# Usage: ./update.sh
#
# Handles: git pull, local-edit snapshot, Docker restart or bare-Python fallback.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_DIR"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()  { echo -e "${GREEN}▶${NC} $*"; }
warn()  { echo -e "${YELLOW}⚠${NC} $*"; }

echo
echo "╔══════════════════════════════════╗"
echo "║     Zikra Server Updater         ║"
echo "╚══════════════════════════════════╝"
echo

# ── 1. Fetch remote ───────────────────────────────────────────────────────────
info "Fetching origin/main …"
git fetch origin main --quiet

PENDING=$(git log HEAD..origin/main --oneline 2>/dev/null || true)
if [ -z "$PENDING" ]; then
    echo "  Already up to date. Nothing to pull."
    exit 0
fi

COMMIT_COUNT=$(echo "$PENDING" | wc -l | tr -d ' ')
echo "  $COMMIT_COUNT commit(s) pending:"
echo "$PENDING" | sed 's/^/    /'
echo

# ── 2. Snapshot local edits if dirty ─────────────────────────────────────────
DIRTY=$(git status --short 2>/dev/null || true)
WIP_BRANCH=""
if [ -n "$DIRTY" ]; then
    WIP_BRANCH="local-wip-$(date +%Y-%m-%d-%H%M%S)"
    warn "Uncommitted local changes detected — snapshotting to branch: $WIP_BRANCH"
    git checkout -b "$WIP_BRANCH" --quiet
    git add -A
    # Use inline identity so the commit works on servers with no global git config
    git -c user.name="Zikra Updater" -c user.email="zikra@localhost" \
        commit -m "wip: local snapshot before update $(date +%Y-%m-%d)" --quiet
    git checkout main --quiet
    echo "  ✓ Local changes saved to branch: $WIP_BRANCH"
fi

# ── 3. Pull ───────────────────────────────────────────────────────────────────
info "Pulling origin/main …"
git pull origin main --quiet
echo "  ✓ Code updated"

# ── 4. Detect runtime and restart ─────────────────────────────────────────────
RUNTIME="bare-python"
CONTAINER_STATUS=""

if docker inspect zikra &>/dev/null 2>&1; then
    RUNTIME="docker"
    MOUNTS=$(docker inspect zikra --format '{{range .Mounts}}{{.Source}} {{end}}' 2>/dev/null || echo "")

    if echo "$MOUNTS" | grep -q "$REPO_DIR"; then
        info "Docker container (bind-mount) detected — restarting …"
        docker restart zikra
        sleep 4
        CONTAINER_STATUS=$(docker inspect --format='{{.State.Health.Status}}' zikra 2>/dev/null || echo "unknown")
        echo "  ✓ Container restarted — health: $CONTAINER_STATUS"
    else
        info "Docker container (image-baked) detected — rebuilding …"
        # Prefer local override compose file if present
        if [ -f docker-compose.local.yml ]; then
            docker compose -f docker-compose.local.yml up -d --build zikra
        elif [ -f docker-compose.yml ] || [ -f docker-compose.yaml ]; then
            docker compose up -d --build zikra
        else
            docker build -t zikra . && docker restart zikra
        fi
        sleep 4
        CONTAINER_STATUS=$(docker inspect --format='{{.State.Health.Status}}' zikra 2>/dev/null || echo "unknown")
        echo "  ✓ Container rebuilt — health: $CONTAINER_STATUS"
    fi
else
    info "No Docker container 'zikra' found — updating Python package …"
    if [ -d ".venv" ]; then
        .venv/bin/pip install -e . --quiet
    else
        pip install -e . --quiet
    fi
    warn "Restart the Zikra process manually (python3 -m zikra) to apply changes."
fi

# ── 5. Summary ────────────────────────────────────────────────────────────────
echo
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║                    Update Summary                            ║"
echo "╠══════════════════════════════════════════════════════════════╣"
printf "║  %-60s ║\n" "Commits pulled:  $COMMIT_COUNT"
printf "║  %-60s ║\n" "Runtime:         $RUNTIME"
[ -n "$CONTAINER_STATUS" ] && printf "║  %-60s ║\n" "Container:       $CONTAINER_STATUS"
[ -n "$WIP_BRANCH" ]       && printf "║  %-60s ║\n" "WIP branch:      $WIP_BRANCH"
echo "╠══════════════════════════════════════════════════════════════╣"
printf "║  %-60s ║\n" "⚠  MCP clients (Claude Code, claude.ai, Cursor) must"
printf "║  %-60s ║\n" "   reconnect after any container restart."
echo "╚══════════════════════════════════════════════════════════════╝"
echo
