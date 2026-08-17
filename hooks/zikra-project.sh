#!/usr/bin/env bash
# zikra-project.sh v2
# Shared project detection for all Zikra hooks. Source this file, then call:
#   zikra_detect_project "<cwd>" "<default_project>"
#
# Resolution order:
#   1. ~/.zikra/projects.map — explicit cwd-prefix mappings, longest prefix
#      wins. One mapping per line: /path/prefix=project-name
#      (written by the installer; edit freely)
#   2. git remote origin — built-in project names only
#   3. git toplevel/directory basename — built-in project names only
# Unknown or missing cwd returns non-zero with no project. Explicit map entries
# are the supported extension point for future project slugs.
#
# Canonical source: zikra/hooks/zikra-project.sh

zikra_detect_project() {
    local cwd="${1:-}"
    [[ -z "$cwd" ]] && return 1

    local builtins=" d2strategy forgenexus global veltisai zikra "
    _zikra_valid_slug() {
        [[ "$1" =~ ^[a-z0-9][a-z0-9_-]{0,63}$ ]]
    }
    _zikra_builtin() {
        [[ "$builtins" == *" $1 "* ]]
    }

    local cwd_l
    cwd_l="$(printf '%s' "$cwd" | tr '[:upper:]' '[:lower:]')"

    # 1. Explicit map — longest boundary-aware prefix wins.
    local map_file="$HOME/.zikra/projects.map"
    if [[ -f "$map_file" ]]; then
        local best="" best_len=0 line prefix project prefix_l
        while IFS= read -r line; do
            [[ -z "$line" || "$line" == \#* || "$line" != *=* ]] && continue
            prefix="${line%%=*}"
            project="${line#*=}"
            prefix_l="$(printf '%s' "$prefix" | tr '[:upper:]' '[:lower:]')"
            project="$(printf '%s' "$project" | tr '[:upper:]' '[:lower:]')"
            if { [[ "$cwd_l" == "$prefix_l" ]] || [[ "$cwd_l" == "$prefix_l/"* ]]; } \
               && [[ ${#prefix_l} -gt $best_len ]] && _zikra_valid_slug "$project"; then
                best="$project"
                best_len=${#prefix_l}
            fi
        done < "$map_file"
        if [[ -n "$best" ]]; then echo "$best"; return; fi
    fi

    # 2. Git remote origin, only for built-in names.
    if command -v git >/dev/null 2>&1; then
        local url repo
        url="$(git -C "$cwd" remote get-url origin 2>/dev/null)"
        if [[ -n "$url" ]]; then
            repo="${url##*/}"
            repo="${repo%.git}"
            repo="${repo##*:}"
            repo="$(printf '%s' "$repo" | tr '[:upper:]' '[:lower:]')"
            if _zikra_builtin "$repo"; then echo "$repo"; return; fi
        fi
        local top top_name
        top="$(git -C "$cwd" rev-parse --show-toplevel 2>/dev/null)"
        if [[ -n "$top" ]]; then
            top_name="$(basename "$top" | tr '[:upper:]' '[:lower:]')"
            if _zikra_builtin "$top_name"; then echo "$top_name"; return; fi
        fi
    fi

    # 3. Cwd basename, only for built-in names and never HOME or root.
    if [[ "$cwd" != "$HOME" && "$cwd" != "/" ]]; then
        local cwd_name
        cwd_name="$(basename "$cwd" | tr '[:upper:]' '[:lower:]')"
        if _zikra_builtin "$cwd_name"; then echo "$cwd_name"; return; fi
    fi
    return 1
}
