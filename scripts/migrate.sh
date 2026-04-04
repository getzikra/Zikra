#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Zikra — Database Migration Runner
#
# Usage:
#   ./scripts/migrate.sh
#
# Reads DB connection from .env in the repo root.
# Applies any pending migrations in migrations/NNN_*.sql (in numeric order).
# Uses zikra.migrations as the version tracking table.
# Safe to run on an up-to-date database — prints "Schema up to date".
# ─────────────────────────────────────────────────────────────────────────────
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# ── Load .env ─────────────────────────────────────────────────────────────────
if [ -f "$REPO_ROOT/.env" ]; then
    set -a
    # shellcheck disable=SC1091
    source "$REPO_ROOT/.env"
    set +a
fi

DB_HOST="${POSTGRES_HOST:-localhost}"
DB_PORT="${POSTGRES_PORT:-5432}"
DB_USER="${POSTGRES_USER:-zikra_user}"
DB_NAME="${POSTGRES_DB:-ai_zikra}"
export PGPASSWORD="${POSTGRES_PASSWORD:-}"

PSQL="psql -h $DB_HOST -p $DB_PORT -U $DB_USER -d $DB_NAME -v ON_ERROR_STOP=1"

# ── Get current max applied version (0 if migrations table missing) ───────────
CURRENT_VERSION=$(
    $PSQL -t -c "SELECT COALESCE(MAX(version), 0) FROM zikra.migrations" \
    2>/dev/null | tr -d '[:space:]'
) || true

if [ -z "$CURRENT_VERSION" ] || ! [[ "$CURRENT_VERSION" =~ ^[0-9]+$ ]]; then
    CURRENT_VERSION=0
fi

# ── Loop through migration files in numeric order ─────────────────────────────
APPLIED=0

for file in $(ls "$REPO_ROOT/migrations"/[0-9][0-9][0-9]_*.sql 2>/dev/null | sort); do
    filename="$(basename "$file")"

    # Extract numeric prefix and strip leading zeros for arithmetic
    raw_version="${filename%%_*}"
    version="${raw_version#"${raw_version%%[!0]*}"}"
    version="${version:-0}"

    if [ "$version" -le "$CURRENT_VERSION" ]; then
        continue
    fi

    description="$(echo "$filename" | sed 's/^[0-9]*_//' | sed 's/\.sql$//' | tr '_' ' ')"

    echo "Applying migration $filename..."
    $PSQL < "$file"

    # Record version (ON CONFLICT in case the migration file inserts itself)
    $PSQL -c "
        INSERT INTO zikra.migrations (version, description)
        VALUES ($version, '$description')
        ON CONFLICT (version) DO NOTHING
    "

    APPLIED=$((APPLIED + 1))
done

if [ "$APPLIED" -eq 0 ]; then
    echo "Schema up to date"
fi
