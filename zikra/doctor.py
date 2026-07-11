"""zikra doctor — self-diagnosis for a Zikra installation.

Checks the whole capture pipeline on this machine: credentials, server
reachability, hook freshness, settings.json wiring, watcher processes
(including split-brain watchers pointing at a different server than the
hooks), and systemd state. Prints ✓/⚠/✗ per check with a fix hint.

Run: python3 -m zikra doctor        (or: python3 installer.py doctor)
Exit code 0 = no failures.
"""

import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

OK, WARN, FAIL = '✓', '⚠', '✗'

REPO_DIR = Path(__file__).parent.parent
HOOKS_SRC = REPO_DIR / 'hooks'
CLAUDE_DIR = Path.home() / '.claude'
CLAUDE_HOOKS_DIR = CLAUDE_DIR / 'hooks'
TOKEN_FILE = Path.home() / '.zikra' / 'token'

# hook file → where the installer puts it
HOOK_DESTS = {
    'zikra_autolog.sh':       CLAUDE_DIR / 'zikra_autolog.sh',
    'notify.sh':              CLAUDE_DIR / 'notify.sh',
    'zikra-project.sh':       CLAUDE_DIR / 'zikra-project.sh',
    'zikra-context.sh':       CLAUDE_HOOKS_DIR / 'zikra-context.sh',
    'zikra-error-capture.sh': CLAUDE_HOOKS_DIR / 'zikra-error-capture.sh',
    'zikra-stats-update.sh':  CLAUDE_HOOKS_DIR / 'zikra-stats-update.sh',
    'zikra-statusline.js':    CLAUDE_HOOKS_DIR / 'zikra-statusline.js',
}

EXPECTED_EVENTS = {
    'Stop':        ['zikra_autolog.sh', 'zikra-stats-update.sh'],
    'PreCompact':  ['zikra_autolog.sh'],
    'SessionStart': ['zikra-context.sh'],
    'PostToolUse': ['zikra-error-capture.sh'],
}


def _read_creds() -> dict:
    creds = {}
    if TOKEN_FILE.exists():
        for line in TOKEN_FILE.read_text().splitlines():
            if '=' in line and not line.startswith('#'):
                k, _, v = line.partition('=')
                creds[k.strip()] = v.strip()
    return creds


def _resolve_placeholders(text: str, creds: dict) -> str:
    return (text
            .replace('ZIKRA_URL_PLACEHOLDER', creds.get('ZIKRA_URL', ''))
            .replace('ZIKRA_TOKEN_PLACEHOLDER', creds.get('ZIKRA_TOKEN', ''))
            .replace('ZIKRA_PROJECT_PLACEHOLDER', creds.get('ZIKRA_PROJECT', 'global'))
            .replace('DEFAULT_PROJECT_PLACEHOLDER', creds.get('ZIKRA_PROJECT', 'global')))


def _post(url: str, token: str, body: dict, timeout: int = 8) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={'Authorization': f'Bearer {token}',
                 'Content-Type': 'application/json',
                 'User-Agent': 'zikra-doctor/1.0'},
        method='POST')
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def _find_watcher_processes() -> list:
    """Scan /proc for running zikra_watcher processes (ps truncates cmdlines
    and misses detached processes — /proc is ground truth)."""
    found = []
    proc = Path('/proc')
    if not proc.exists():
        return found
    for p in proc.iterdir():
        if not p.name.isdigit():
            continue
        try:
            cmdline = (p / 'cmdline').read_bytes().replace(b'\x00', b' ').decode(errors='replace')
        except OSError:
            continue
        if 'zikra_watcher' in cmdline:
            script = next((a for a in cmdline.split() if 'zikra_watcher' in a), '')
            found.append({'pid': int(p.name), 'cmdline': cmdline.strip(), 'script': script})
    return found


def _extract_url(script_path: str) -> str:
    """Pull the effective ZIKRA_URL out of an installed watcher/hook script."""
    try:
        text = Path(os.path.expanduser(script_path)).read_text()
    except OSError:
        return ''
    m = re.search(r'ZIKRA_URL\s*=\s*["\']([^"\']+)["\']', text)
    url = m.group(1) if m else ''
    return '' if 'PLACEHOLDER' in url else url


def run_doctor(json_output: bool = False) -> int:
    checks = []

    def check(status, name, detail='', fix=''):
        checks.append({'status': status, 'name': name, 'detail': detail, 'fix': fix})

    creds = _read_creds()
    url = creds.get('ZIKRA_URL', '')
    token = creds.get('ZIKRA_TOKEN', '')

    # 1 — credentials file
    if not TOKEN_FILE.exists():
        check(FAIL, 'credentials', f'{TOKEN_FILE} missing',
              'run: python3 installer.py')
    elif not url or not token:
        check(FAIL, 'credentials', f'{TOKEN_FILE} lacks ZIKRA_URL or ZIKRA_TOKEN',
              'run: python3 installer.py')
    else:
        check(OK, 'credentials', f'{TOKEN_FILE} → {url}')

    # 2 — server reachability + auth + distiller
    if url and token:
        base = url.rsplit('/webhook/', 1)[0]
        try:
            with urllib.request.urlopen(f'{base}/health', timeout=5) as resp:
                health = json.loads(resp.read().decode())
            version = health.get('version', '?')
            latest = health.get('latest_version')
            if latest and latest != version:
                check(WARN, 'server', f'reachable, v{version} (v{latest} available)',
                      'run: zikra update')
            else:
                check(OK, 'server', f'reachable, v{version}')
            if 'distiller' in health:
                if health['distiller']:
                    check(OK, 'distiller', 'server-side distillation enabled')
                else:
                    check(WARN, 'distiller', 'no LLM configured on server — hooks fall back to local claude -p',
                          'set ZIKRA_LLM_API_KEY (or OPENAI_API_KEY) in the server .env')
        except Exception as e:
            check(FAIL, 'server', f'{base}/health unreachable: {e}',
                  'start the server: python3 -m zikra --no-onboarding')
        try:
            v = _post(url, token, {'command': 'version'})
            if v.get('error'):
                check(FAIL, 'auth', f'token rejected: {v}', 'check ZIKRA_TOKEN in ~/.zikra/token vs server .env')
            else:
                check(OK, 'auth', 'webhook token accepted')
        except Exception as e:
            check(FAIL, 'auth', f'webhook call failed: {e}')

    # 3 — installed hooks: present + fresh
    for name, dest in HOOK_DESTS.items():
        src = HOOKS_SRC / name
        if not src.exists():
            continue
        if not dest.exists():
            check(WARN, f'hook:{name}', f'not installed at {dest}',
                  'run: python3 installer.py  (or zikra update)')
            continue
        expected = _resolve_placeholders(src.read_text(), creds)
        if dest.read_text() != expected:
            check(WARN, f'hook:{name}', 'installed copy differs from repo version',
                  'run: zikra update')
        else:
            check(OK, f'hook:{name}', 'installed and current')

    # 4 — settings.json wiring
    settings_path = CLAUDE_DIR / 'settings.json'
    try:
        settings = json.loads(settings_path.read_text())
    except Exception:
        settings = None
        check(WARN, 'settings.json', f'{settings_path} missing or invalid JSON',
              'run: python3 installer.py')
    if settings is not None:
        hooks_cfg = settings.get('hooks', {})
        for event, needles in EXPECTED_EVENTS.items():
            cmds = ' '.join(
                h.get('command', '')
                for m in hooks_cfg.get(event, [])
                for h in m.get('hooks', [])
            )
            missing = [n for n in needles if n not in cmds]
            dupes = [n for n in needles if cmds.count(n) > 1]
            if missing:
                check(WARN, f'wiring:{event}', f'missing {", ".join(missing)}',
                      'run: python3 installer.py')
            elif dupes:
                check(WARN, f'wiring:{event}', f'duplicate entries for {", ".join(dupes)}',
                      'run: python3 installer.py (normalizes hook lists)')
            else:
                check(OK, f'wiring:{event}', 'wired')
        mcp = (settings.get('mcpServers') or {}).get('zikra', {})
        if not mcp:
            check(WARN, 'wiring:mcp', 'zikra MCP server not registered',
                  'run: python3 installer.py')
        else:
            check(OK, 'wiring:mcp', mcp.get('url', ''))

    # 5 — watcher processes: split-brain and duplicates
    watchers = _find_watcher_processes()
    if len(watchers) > 1:
        check(FAIL, 'watcher', f'{len(watchers)} watcher processes running (pids '
              f'{", ".join(str(w["pid"]) for w in watchers)}) — sessions will double-log',
              'kill the extras; keep one systemd-managed watcher')
    for w in watchers:
        w_url = _extract_url(w['script']) if w['script'] else ''
        if w_url and url and w_url.rstrip('/') != url.rstrip('/'):
            check(FAIL, 'watcher:split-brain',
                  f'pid {w["pid"]} posts to {w_url} but hooks post to {url}',
                  f'kill pid {w["pid"]}, delete its script, reinstall via installer.py')
        elif w_url:
            check(OK, 'watcher', f'pid {w["pid"]} → {w_url}')

    # stale watcher file on disk (even if not running)
    for cand in (CLAUDE_DIR / 'zikra_watcher.py',):
        if cand.exists():
            repo_watcher = REPO_DIR / 'daemon' / 'zikra_watcher.py'
            if repo_watcher.exists():
                expected = _resolve_placeholders(repo_watcher.read_text(), creds)
                if cand.read_text() != expected:
                    check(WARN, 'watcher:file', f'{cand} differs from repo daemon (stale version?)',
                          'run: zikra update, or reinstall the full profile')
        f_url = _extract_url(str(cand))
        if f_url and url and f_url.rstrip('/') != url.rstrip('/'):
            check(FAIL, 'watcher:file', f'{cand} hardcodes {f_url} ≠ {url}',
                  'delete it and reinstall via installer.py')

    # 6 — systemd units
    if sys.platform.startswith('linux'):
        for unit in ('zikra.service', 'zikra_watcher.service'):
            try:
                r = subprocess.run(['systemctl', '--user', 'is-enabled', unit],
                                   capture_output=True, text=True, timeout=5)
                state = r.stdout.strip()
            except Exception:
                state = ''
            if state == 'enabled':
                try:
                    a = subprocess.run(['systemctl', '--user', 'is-active', unit],
                                       capture_output=True, text=True, timeout=5)
                    active = a.stdout.strip()
                except Exception:
                    active = '?'
                if active == 'active':
                    check(OK, f'systemd:{unit}', 'enabled and active')
                else:
                    check(WARN, f'systemd:{unit}', f'enabled but {active}',
                          f'systemctl --user restart {unit}; journalctl --user -u {unit}')

    # ── Report ────────────────────────────────────────────────────────────────
    if json_output:
        print(json.dumps(checks, indent=2, ensure_ascii=False))
    else:
        print('\nzikra doctor\n' + '─' * 60)
        for c in checks:
            print(f' {c["status"]} {c["name"]:<28} {c["detail"]}')
            if c['fix'] and c['status'] != OK:
                print(f'   └─ fix: {c["fix"]}')
        fails = sum(1 for c in checks if c['status'] == FAIL)
        warns = sum(1 for c in checks if c['status'] == WARN)
        print('─' * 60)
        print(f' {len(checks)} checks: {fails} failed, {warns} warnings\n')

    return 1 if any(c['status'] == FAIL for c in checks) else 0


if __name__ == '__main__':
    sys.exit(run_doctor('--json' in sys.argv))
