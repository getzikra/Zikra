#!/usr/bin/env bash
# zikra-project.sh v2
# Shared project detection for all Zikra hooks. Source this file, then call:
#   zikra_detect_project "<cwd>" "<default_project>"
#
# Resolution order:
#   1. A2K_PROJECT environment override
#   2. nearest authorized .a2k/manifest.yaml metadata.name
#   3. ~/.zikra/projects.map explicit cwd-prefix mapping, longest prefix wins
#   4. git remote origin repository name
#   5. git toplevel directory basename (non-git: cwd basename)
#   6. the provided default
#
# A repository-controlled manifest is discovery data, not authorization. Its
# project name is accepted only when it matches the local projects.map binding
# or the checkout's origin repository name.
#
# Canonical source: zikra/hooks/zikra-project.sh

_zikra_manifest_project_name() {
    local manifest_path="$1"
    python3 - "$manifest_path" <<'PY' 2>/dev/null
import re
import sys

try:
    with open(sys.argv[1], "rb") as handle:
        content = handle.read(1024 * 1024 + 1)
except OSError:
    raise SystemExit(0)
if len(content) > 1024 * 1024:
    raise SystemExit(0)
try:
    lines = content.decode("utf-8").splitlines()
except UnicodeError:
    raise SystemExit(0)

in_metadata = False
for line in lines:
    if not line.strip() or line.lstrip().startswith("#"):
        continue
    indent = len(line) - len(line.lstrip(" "))
    if indent == 0:
        in_metadata = line.strip() == "metadata:"
        continue
    if in_metadata and indent == 2 and line.lstrip().startswith("name:"):
        match = re.fullmatch(r"  name:\s*([a-z][a-z0-9-]{0,62})\s*", line)
        if match:
            print(match.group(1))
        raise SystemExit(0)
PY
}

zikra_detect_project() {
    local cwd="${1:-}"
    local default="${2:-global}"
    [[ -z "$cwd" ]] && { echo "$default"; return; }

    if [[ -n "${A2K_PROJECT:-}" ]]; then
        printf '%s\n' "$A2K_PROJECT"
        return
    fi

    local cwd_l
    cwd_l="$(printf '%s' "$cwd" | tr '[:upper:]' '[:lower:]')"

    # Resolve the trusted local map binding without returning yet. It can
    # authorize a manifest whose project name intentionally differs from git.
    local map_project="" map_file="$HOME/.zikra/projects.map"
    if [[ -f "$map_file" ]]; then
        local best_len=0 line prefix project prefix_l
        while IFS= read -r line; do
            [[ -z "$line" || "$line" == \#* || "$line" != *=* ]] && continue
            prefix="${line%%=*}"
            project="${line#*=}"
            prefix_l="$(printf '%s' "$prefix" | tr '[:upper:]' '[:lower:]')"
            if [[ "$cwd_l" == "$prefix_l"* && ${#prefix_l} -gt $best_len ]]; then
                map_project="$project"
                best_len=${#prefix_l}
            fi
        done < "$map_file"
    fi

    # Resolve git evidence once so it can authorize the manifest and remain a
    # fallback when no authorized manifest is present.
    local git_project="" git_top=""
    if command -v git >/dev/null 2>&1; then
        local url
        url="$(git -C "$cwd" remote get-url origin 2>/dev/null)"
        if [[ -n "$url" ]]; then
            git_project="${url##*/}"
            git_project="${git_project%.git}"
            git_project="$(printf '%s' "$git_project" | tr '[:upper:]' '[:lower:]')"
        fi
        git_top="$(git -C "$cwd" rev-parse --show-toplevel 2>/dev/null)"
    fi

    local manifest_dir="$cwd" manifest_path manifest_name parent
    while [[ -n "$manifest_dir" ]]; do
        manifest_path="$manifest_dir/.a2k/manifest.yaml"
        if [[ -f "$manifest_path" && ! -L "$manifest_path" ]]; then
            manifest_name="$(_zikra_manifest_project_name "$manifest_path")"
            if [[ -n "$manifest_name" && (
                "$manifest_name" == "$map_project" ||
                (-z "$map_project" && "$manifest_name" == "$git_project")
            ) ]]; then
                printf '%s\n' "$manifest_name"
                return
            fi
            break
        fi
        [[ "$manifest_dir" == "/" ]] && break
        parent="$(dirname "$manifest_dir")"
        [[ "$parent" == "$manifest_dir" ]] && break
        manifest_dir="$parent"
    done

    if [[ -n "$map_project" ]]; then
        printf '%s\n' "$map_project"
        return
    fi
    if [[ -n "$git_project" ]]; then
        printf '%s\n' "$git_project"
        return
    fi
    if [[ -n "$git_top" ]]; then
        basename "$git_top" | tr '[:upper:]' '[:lower:]'
        return
    fi

    if [[ "$cwd" != "$HOME" && "$cwd" != "/" ]]; then
        basename "$cwd" | tr '[:upper:]' '[:lower:]'
        return
    fi

    echo "$default"
}
