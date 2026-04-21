#!/bin/bash
# Zikra shell statusline — for Gemini CLI and Codex CLI sessions
#
# Source this file in ~/.bashrc or ~/.zshrc and it will print the Zikra
# status bar before every shell prompt, reusing the same zikra-statusline.js
# renderer that Claude Code uses.
#
# The installer adds this automatically. To add manually:
#   echo 'source ~/.claude/hooks/zikra-shell-status.sh' >> ~/.bashrc
#
# How it works:
#   - Reads the last_tool and last_model from the shared cache
#   - Pipes a synthetic payload to zikra-statusline.js
#   - No token bar (context window data not available at shell level)
#   - Skips gracefully if Node.js or the cache is absent

_zikra_shell_status() {
    local statusline="$HOME/.claude/hooks/zikra-statusline.js"
    local cache="$HOME/.claude/cache/zikra-stats.json"

    # Bail if the renderer or cache is missing, or Node isn't available
    [[ -f "$statusline" && -f "$cache" ]] || return 0
    command -v node >/dev/null 2>&1 || return 0

    # Build a minimal payload from the cache so the renderer knows the model.
    # We omit context_window intentionally — no token bar in shell mode.
    local model
    model=$(python3 -c "
import json, sys
try:
    d = json.load(open('$cache'))
    # Show the last tool name next to the model when it isn't claude
    tool  = d.get('last_tool', '')
    model = d.get('last_model', '')
    if tool and tool != 'claude' and model and not model.lower().startswith(tool.lower()):
        print(f'{tool}/{model}')
    else:
        print(model or '')
except:
    print('')
" 2>/dev/null) || model=""

    # Pipe the payload; zikra-statusline.js reads stdin with a 200ms deadline
    printf '{"model":"%s"}' "$model" | node "$statusline" 2>/dev/null
}

# ── Wire up to the shell ──────────────────────────────────────────────────────

if [[ -n "$ZSH_VERSION" ]]; then
    # zsh: use add-zsh-hook so we don't clobber existing precmd hooks
    autoload -Uz add-zsh-hook 2>/dev/null
    add-zsh-hook precmd _zikra_shell_status 2>/dev/null
elif [[ -n "$BASH_VERSION" ]]; then
    # bash: append to PROMPT_COMMAND; preserve any existing value
    if [[ -z "$PROMPT_COMMAND" ]]; then
        PROMPT_COMMAND="_zikra_shell_status"
    else
        PROMPT_COMMAND="${PROMPT_COMMAND%;}; _zikra_shell_status"
    fi
fi
