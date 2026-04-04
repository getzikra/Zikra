#!/bin/bash
# Zikra cross-platform notification
# Works on WSL, Linux, Mac, Windows Git Bash, Termux

MESSAGE="${1:-Zikra session complete}"
TITLE="${2:-Zikra}"

# Detect environment
detect_env() {
    if [[ "$OSTYPE" == "darwin"* ]]; then
        echo "mac"
    elif grep -qi microsoft /proc/version 2>/dev/null; then
        echo "wsl"
    elif [[ "$OSTYPE" == "msys" || "$OSTYPE" == "cygwin" ]]; then
        echo "windows_bash"
    elif command -v termux-notification &>/dev/null; then
        echo "termux"
    else
        echo "linux"
    fi
}

ENV=$(detect_env)

# Sanitize for AppleScript double-quoted strings: strip `$` and backticks (shell injection),
# double backslashes, then escape double quotes.
_safe_apl() { printf '%s' "$1" | tr -d '`$' | sed 's/\\/\\\\/g; s/"/\\"/g'; }

# Sanitize for PowerShell single-quoted strings: strip `$`, backticks, backslashes
# (PowerShell backtick is the escape char), then double single quotes.
_safe_ps() { printf '%s' "$1" | tr -d '`$\\' | sed "s/'/''/g"; }

case "$ENV" in
    mac)
        MSG_SAFE=$(_safe_apl "$MESSAGE")
        TTL_SAFE=$(_safe_apl "$TITLE")
        osascript -e "display notification \"$MSG_SAFE\" with title \"$TTL_SAFE\"" 2>/dev/null
        ;;
    wsl)
        # Try Windows toast notification via PowerShell if interop enabled
        if command -v powershell.exe &>/dev/null; then
            MSG_SAFE=$(_safe_ps "$MESSAGE")
            TTL_SAFE=$(_safe_ps "$TITLE")
            powershell.exe -Command "
                Add-Type -AssemblyName System.Windows.Forms
                \$n = New-Object System.Windows.Forms.NotifyIcon
                \$n.Icon = [System.Drawing.SystemIcons]::Information
                \$n.Visible = \$true
                \$n.ShowBalloonTip(3000, '$TTL_SAFE', '$MSG_SAFE',
                [System.Windows.Forms.ToolTipIcon]::Info)
                Start-Sleep -Seconds 4
                \$n.Dispose()
            " 2>/dev/null &
        elif command -v notify-send &>/dev/null; then
            notify-send "$TITLE" "$MESSAGE" 2>/dev/null
        else
            echo "[Zikra] $MESSAGE"
        fi
        ;;
    windows_bash)
        if command -v powershell.exe &>/dev/null; then
            MSG_SAFE=$(_safe_ps "$MESSAGE")
            TTL_SAFE=$(_safe_ps "$TITLE")
            powershell.exe -Command "
                [System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms')
                \$n = New-Object System.Windows.Forms.NotifyIcon
                \$n.Icon = [System.Drawing.SystemIcons]::Information
                \$n.Visible = \$true
                \$n.ShowBalloonTip(3000, '$TTL_SAFE', '$MSG_SAFE',
                [System.Windows.Forms.ToolTipIcon]::Info)
                Start-Sleep -Seconds 4
                \$n.Dispose()
            " 2>/dev/null &
        else
            echo "[Zikra] $MESSAGE"
        fi
        ;;
    termux)
        termux-notification --title "$TITLE" --content "$MESSAGE" 2>/dev/null
        ;;
    linux)
        if command -v notify-send &>/dev/null; then
            notify-send "$TITLE" "$MESSAGE" 2>/dev/null
        else
            echo "[Zikra] $MESSAGE"
        fi
        ;;
esac

exit 0
