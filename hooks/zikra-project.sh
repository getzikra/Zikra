#!/usr/bin/env bash
# zikra-project.sh v1
# Shared project detection for all Zikra hooks. Source this file, then call:
#   zikra_detect_project "<cwd>" "<default_project>"
#
# Resolution order:
#   1. ~/.zikra/projects.map — explicit cwd-prefix mappings, longest prefix
#      wins. One mapping per line: /path/prefix=project-name
#      (written by the installer; edit freely)
#   2. git remote origin — repository name, lowercased
#   3. git toplevel directory basename (non-git: cwd basename)
#   4. the provided default
#
# Canonical source: zikra/hooks/zikra-project.sh

zikra_detect_project() {
    local cwd="${1:-}"
    local default="${2:-global}"
    [[ -z "$cwd" ]] && { echo "$default"; return; }

    local cwd_l
    cwd_l="$(printf '%s' "$cwd" | tr '[:upper:]' '[:lower:]')"

    # 1. Explicit map — longest matching prefix wins
    local map_file="$HOME/.zikra/projects.map"
    if [[ -f "$map_file" ]]; then
        local best="" best_len=0 line prefix project prefix_l
        while IFS= read -r line; do
            [[ -z "$line" || "$line" == \#* || "$line" != *=* ]] && continue
            prefix="${line%%=*}"
            project="${line#*=}"
            prefix_l="$(printf '%s' "$prefix" | tr '[:upper:]' '[:lower:]')"
            if [[ "$cwd_l" == "$prefix_l"* && ${#prefix_l} -gt $best_len ]]; then
                best="$project"
                best_len=${#prefix_l}
            fi
        done < "$map_file"
        if [[ -n "$best" ]]; then echo "$best"; return; fi
    fi

    # 2. git remote origin → repo name
    if command -v git >/dev/null 2>&1; then
        local url repo
        url="$(git -C "$cwd" remote get-url origin 2>/dev/null)"
        if [[ -n "$url" ]]; then
            repo="${url##*/}"
            repo="${repo%.git}"
            repo="$(printf '%s' "$repo" | tr '[:upper:]' '[:lower:]')"
            if [[ -n "$repo" ]]; then echo "$repo"; return; fi
        fi
        # 3a. git toplevel basename
        local top
        top="$(git -C "$cwd" rev-parse --show-toplevel 2>/dev/null)"
        if [[ -n "$top" ]]; then
            basename "$top" | tr '[:upper:]' '[:lower:]'
            return
        fi
    fi

    # 3b. cwd basename, unless it is the home directory or /
    if [[ "$cwd" != "$HOME" && "$cwd" != "/" ]]; then
        basename "$cwd" | tr '[:upper:]' '[:lower:]'
        return
    fi

    echo "$default"
}
