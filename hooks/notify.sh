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

case "$ENV" in
    mac)
        osascript -e "display notification \"$MESSAGE\" with title \"$TITLE\"" 2>/dev/null
        ;;
    wsl)
        # Try Windows toast notification via PowerShell if interop enabled
        if command -v powershell.exe &>/dev/null; then
            powershell.exe -Command "
                Add-Type -AssemblyName System.Windows.Forms
                \$n = New-Object System.Windows.Forms.NotifyIcon
                \$n.Icon = [System.Drawing.SystemIcons]::Information
                \$n.Visible = \$true
                \$n.ShowBalloonTip(3000, '$TITLE', '$MESSAGE',
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
            powershell.exe -Command "
                [System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms')
                \$n = New-Object System.Windows.Forms.NotifyIcon
                \$n.Icon = [System.Drawing.SystemIcons]::Information
                \$n.Visible = \$true
                \$n.ShowBalloonTip(3000, '$TITLE', '$MESSAGE',
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
