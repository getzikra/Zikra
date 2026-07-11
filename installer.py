#!/usr/bin/env python3
"""
Zikra unified installer.

Interactive:      python3 installer.py
Non-interactive:  python3 installer.py --non-interactive [flags]
Self-diagnosis:   python3 installer.py doctor
"""

import argparse
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
from pathlib import Path

HOOKS_SRC = Path(__file__).parent / 'hooks'
CLAUDE_DIR = Path.home() / '.claude'
CLAUDE_HOOKS_DIR = CLAUDE_DIR / 'hooks'


# ── CLI ───────────────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(description='Zikra installer')
    p.add_argument('command', nargs='?', choices=['install', 'doctor'], default='install')
    p.add_argument('--non-interactive', action='store_true',
                   help='no prompts; configure from flags/env and defaults')
    p.add_argument('--db', choices=['sqlite', 'postgres'],
                   default=os.getenv('ZIKRA_INSTALL_DB', 'sqlite'))
    p.add_argument('--profile', choices=['webhook', 'autolog', 'full'],
                   default=os.getenv('ZIKRA_INSTALL_PROFILE', 'autolog'))
    p.add_argument('--project', default=os.getenv('ZIKRA_PROJECT', 'main'))
    p.add_argument('--host', default=os.getenv('ZIKRA_HOST', '0.0.0.0'))
    p.add_argument('--port', default=os.getenv('ZIKRA_PORT', '8000'))
    p.add_argument('--openai-key', default=os.getenv('OPENAI_API_KEY', ''))
    p.add_argument('--llm-base-url', default=os.getenv('ZIKRA_LLM_BASE_URL', ''),
                   help='OpenAI-compatible endpoint for the server-side distiller (e.g. LiteLLM)')
    p.add_argument('--llm-model', default=os.getenv('ZIKRA_LLM_MODEL', ''))
    p.add_argument('--llm-api-key', default=os.getenv('ZIKRA_LLM_API_KEY', ''))
    p.add_argument('--with-codex', action='store_true', help='install Codex CLI hooks')
    p.add_argument('--with-kimi', action='store_true', help='install Kimi CLI hooks')
    p.add_argument('--with-gemini', action='store_true',
                   help='install Gemini CLI hooks (no longer offered interactively)')
    p.add_argument('--json', action='store_true', help='doctor: JSON output')
    # postgres connection (non-interactive)
    p.add_argument('--pg-host', default=os.getenv('DB_HOST', 'localhost'))
    p.add_argument('--pg-port', default=os.getenv('DB_PORT', '5432'))
    p.add_argument('--pg-name', default=os.getenv('DB_NAME', ''))
    p.add_argument('--pg-user', default=os.getenv('DB_USER', ''))
    p.add_argument('--pg-password', default=os.getenv('DB_PASSWORD', ''))
    return p.parse_args()


# ── Question helpers ──────────────────────────────────────────────────────────

def _ask(prompt, default=None, validate=None):
    while True:
        suffix = f' [{default}]' if default is not None else ''
        raw = input(f'{prompt}{suffix}: ').strip()
        val = raw if raw else (str(default) if default is not None else '')
        if validate:
            err = validate(val)
            if err:
                print(f'  ✗ {err}')
                continue
        return val


def _ask_choice(prompt, choices, default='1'):
    return _ask(prompt, default=default,
                validate=lambda v: f'Enter one of: {", ".join(choices)}' if v not in choices else None)


def _validate_project(v):
    if not v:
        return 'Project name cannot be empty'
    if not re.match(r'^[a-z0-9][a-z0-9\-]*$', v):
        return 'Only lowercase letters, numbers, and hyphens allowed. No spaces or uppercase.'
    return None


# ── Config gathering ──────────────────────────────────────────────────────────

def gather_interactive(args) -> dict:
    print()
    print('╔═══════════════════════════════════════╗')
    print('║         Zikra Installer               ║')
    print('║   Persistent memory for AI agents     ║')
    print('╚═══════════════════════════════════════╝')
    print()

    cfg = {}

    print('Where should Zikra store data?')
    print('  [1] SQLite — local file, zero setup (recommended for personal use)')
    print('  [2] PostgreSQL — external database (recommended for teams)')
    db_choice = _ask_choice('  Choice', ['1', '2'], default='1')
    cfg['db_backend'] = 'postgres' if db_choice == '2' else 'sqlite'

    if cfg['db_backend'] == 'postgres':
        print()
        cfg['pg_host'] = _ask('  Postgres host', default='localhost')
        cfg['pg_port'] = _ask('  Postgres port', default='5432',
                              validate=lambda v: 'Must be a valid port number' if not v.isdigit() else None)
        cfg['pg_name'] = _ask('  Postgres database name')
        cfg['pg_user'] = _ask('  Postgres user')
        cfg['pg_password'] = _ask('  Postgres password')

    print()
    print('How deeply should Zikra integrate with Claude Code?')
    print('  [1] Webhook only — just the API, no file hooks')
    print('  [2] Auto-log — installs hooks: session capture, auto-recall context,')
    print('      error capture, statusline (recommended)')
    print('  [3] Full — auto-log + background watcher daemon + systemd service')
    hook_choice = _ask_choice('  Choice', ['1', '2', '3'], default='2')
    cfg['profile'] = {'1': 'webhook', '2': 'autolog', '3': 'full'}[hook_choice]

    print()
    print('Do you have an OpenAI API key for semantic search? (leave blank to skip)')
    cfg['openai_key'] = _ask('  Key', default='',
                             validate=lambda v: None if not v or (v.startswith('sk-') and len(v) >= 8) else
                                      "Must start with 'sk-' or leave blank to skip")
    if not cfg['openai_key']:
        print('  WARNING: Running in keyword-only mode. '
              'Add OPENAI_API_KEY to .env later to enable semantic search.')

    print()
    print('Server-side distiller (turns session transcripts into typed memories).')
    print('Uses the OpenAI key above by default; point it at LiteLLM/OpenRouter here.')
    cfg['llm_base_url'] = _ask('  LLM base URL (blank = api.openai.com)', default='')
    cfg['llm_model'] = _ask('  LLM model (blank = gpt-4o-mini)', default='')
    cfg['llm_api_key'] = ''
    if cfg['llm_base_url']:
        cfg['llm_api_key'] = _ask('  LLM API key (blank = reuse OpenAI key)', default='')

    print()
    cfg['project'] = _ask('  Default project name for this installation', default='main',
                          validate=_validate_project)

    print()
    cfg['host'] = _ask(' Zikra bind host', default='0.0.0.0')
    cfg['port'] = _ask(' Zikra server port', default='8000',
                       validate=lambda v: 'Must be a valid port number' if not v.isdigit() else None)

    _codex_found = bool(shutil.which('codex'))
    _kimi_found = bool(shutil.which('kimi') or shutil.which('kimi-code'))
    print()
    print('Other AI coding tools to integrate with?')
    print('  Zikra hooks for these tools capture sessions and feed the shared statusline.')
    print(f'  [1] Claude Code only')
    print(f'  [2] Codex CLI{"   (detected)" if _codex_found else ""}')
    print(f'  [3] Kimi CLI{"    (detected)" if _kimi_found else ""}')
    print(f'  [4] Both Codex and Kimi')
    tools = _ask_choice('  Choice', ['1', '2', '3', '4'], default='1')
    cfg['install_codex'] = tools in ('2', '4')
    cfg['install_kimi'] = tools in ('3', '4')
    cfg['install_gemini'] = args.with_gemini  # legacy, flag-only
    return cfg


def gather_non_interactive(args) -> dict:
    cfg = {
        'db_backend': args.db,
        'profile': args.profile,
        'openai_key': args.openai_key,
        'llm_base_url': args.llm_base_url,
        'llm_model': args.llm_model,
        'llm_api_key': args.llm_api_key,
        'project': args.project,
        'host': args.host,
        'port': str(args.port),
        'install_codex': args.with_codex,
        'install_kimi': args.with_kimi,
        'install_gemini': args.with_gemini,
        'pg_host': args.pg_host,
        'pg_port': str(args.pg_port),
        'pg_name': args.pg_name,
        'pg_user': args.pg_user,
        'pg_password': args.pg_password,
    }
    err = _validate_project(cfg['project'])
    if err:
        print(f'ERROR: --project: {err}', file=sys.stderr)
        sys.exit(1)
    if cfg['db_backend'] == 'postgres' and not (cfg['pg_name'] and cfg['pg_user']):
        print('ERROR: postgres mode needs --pg-name and --pg-user (or DB_NAME/DB_USER env)',
              file=sys.stderr)
        sys.exit(1)
    return cfg


# ── Install steps ─────────────────────────────────────────────────────────────

def write_env(cfg, token) -> None:
    default_model = ('text-embedding-3-large' if cfg['db_backend'] == 'postgres'
                     else 'text-embedding-3-small')
    lines = [
        f'ZIKRA_TOKEN={token}',
        'ZIKRA_SKIP_ONBOARDING=1',
        f'OPENAI_API_KEY={cfg["openai_key"]}',
        f'ZIKRA_EMBEDDING_MODEL={default_model}',
        f'DB_BACKEND={cfg["db_backend"]}',
    ]
    if cfg['db_backend'] == 'postgres':
        lines += [
            f'DB_HOST={cfg["pg_host"]}',
            f'DB_PORT={cfg["pg_port"]}',
            f'DB_NAME={cfg["pg_name"]}',
            f'DB_USER={cfg["pg_user"]}',
            f'DB_PASSWORD={cfg["pg_password"]}',
        ]
    if cfg.get('llm_base_url'):
        lines.append(f'ZIKRA_LLM_BASE_URL={cfg["llm_base_url"]}')
    if cfg.get('llm_model'):
        lines.append(f'ZIKRA_LLM_MODEL={cfg["llm_model"]}')
    if cfg.get('llm_api_key'):
        lines.append(f'ZIKRA_LLM_API_KEY={cfg["llm_api_key"]}')
    lines += [
        f'ZIKRA_HOST={cfg["host"]}',
        f'ZIKRA_PORT={cfg["port"]}',
        f'ZIKRA_PROJECT={cfg["project"]}',
    ]
    Path('.env').write_text('\n'.join(lines) + '\n')
    print('✓ .env written')
    cfg['embedding_model'] = default_model


def make_hook_installer(cfg, token):
    def _install_hook(src_name, dst_path):
        src = HOOKS_SRC / src_name
        content = src.read_text()
        content = content.replace('ZIKRA_TOKEN_PLACEHOLDER', token)
        content = content.replace('ZIKRA_URL_PLACEHOLDER',
                                  f'http://{cfg["host"]}:{cfg["port"]}/webhook/zikra')
        content = content.replace('ZIKRA_PROJECT_PLACEHOLDER', cfg['project'])
        content = content.replace('DEFAULT_PROJECT_PLACEHOLDER', cfg['project'])
        dst_path.write_text(content)
        dst_path.chmod(0o755)
        print(f'  ✓ installed {dst_path}')
    return _install_hook


def install_claude_hooks(cfg, _install_hook) -> None:
    CLAUDE_DIR.mkdir(parents=True, exist_ok=True)
    CLAUDE_HOOKS_DIR.mkdir(parents=True, exist_ok=True)
    _install_hook('zikra_autolog.sh', CLAUDE_DIR / 'zikra_autolog.sh')
    _install_hook('notify.sh', CLAUDE_DIR / 'notify.sh')
    _install_hook('zikra-project.sh', CLAUDE_DIR / 'zikra-project.sh')
    _install_hook('zikra-statusline.js', CLAUDE_HOOKS_DIR / 'zikra-statusline.js')
    _install_hook('zikra-stats-update.sh', CLAUDE_HOOKS_DIR / 'zikra-stats-update.sh')
    # v1.1.0: auto-recall at session start + automatic error capture
    _install_hook('zikra-context.sh', CLAUDE_HOOKS_DIR / 'zikra-context.sh')
    _install_hook('zikra-error-capture.sh', CLAUDE_HOOKS_DIR / 'zikra-error-capture.sh')


def write_projects_map(cfg) -> None:
    """Seed ~/.zikra/projects.map so users see how cwd→project mapping works."""
    map_file = Path.home() / '.zikra' / 'projects.map'
    if map_file.exists():
        return
    map_file.parent.mkdir(parents=True, exist_ok=True)
    map_file.write_text(
        '# Zikra project mapping — one per line: /path/prefix=project-name\n'
        '# Longest matching prefix wins. Unmatched paths fall back to the git\n'
        '# remote repo name, then the directory basename.\n'
        f'# Example: {Path.home()}/work/acme=acme\n'
    )
    print(f'  ✓ project map template at {map_file}')


def install_codex_hooks(cfg, _install_hook) -> None:
    codex_dir = Path.home() / '.codex'
    hook_dst = CLAUDE_HOOKS_DIR / 'codex-hook.sh'
    _install_hook('codex-hook.sh', hook_dst)
    codex_dir.mkdir(parents=True, exist_ok=True)

    config_toml = codex_dir / 'config.toml'
    hooks_json = codex_dir / 'hooks.json'
    if config_toml.exists():
        content = config_toml.read_text()
        hook_block = (
            f'\n[hooks]\n'
            f'Stop        = ["{hook_dst}"]\n'
            f'PostToolUse = ["{hook_dst}"]\n'
        )
        if '[hooks]' not in content:
            config_toml.write_text(content + hook_block)
            print(f'  ✓ Codex hooks added to {config_toml}')
        else:
            print(f'  NOTE: {config_toml} already has a [hooks] section — add manually:')
            print(f'    Stop        = ["{hook_dst}"]')
            print(f'    PostToolUse = ["{hook_dst}"]')
    else:
        try:
            existing = json.loads(hooks_json.read_text()) if hooks_json.exists() else {}
        except (json.JSONDecodeError, ValueError):
            existing = {}
        for event in ('Stop', 'PostToolUse'):
            entries = existing.setdefault(event, [])
            entries[:] = [e for e in entries if e.get('name') != 'zikra']
            entries.append({'name': 'zikra', 'command': str(hook_dst)})
        tmp = str(hooks_json) + '.tmp'
        with open(tmp, 'w') as f:
            json.dump(existing, f, indent=2)
        os.replace(tmp, str(hooks_json))
        print(f'  ✓ Codex hooks registered in {hooks_json}')


def install_kimi_hooks(cfg, _install_hook) -> None:
    """Kimi CLI (~/.kimi) and Kimi Code CLI (~/.kimi-code) — [[hooks]] TOML.

    Kimi hooks speak the Claude Code stdin protocol, so we register:
      Stop + SessionEnd → kimi-hook.sh (transcript capture + distillation)
      PostToolUse       → zikra-error-capture.sh (Kimi sends tool_output)
      SessionStart      → zikra-context.sh --plain (stdout joins context)
    Only event/command/matcher/timeout keys are legal in a [[hooks]] block.
    """
    hook_dst = CLAUDE_HOOKS_DIR / 'kimi-hook.sh'
    _install_hook('kimi-hook.sh', hook_dst)
    err_hook = CLAUDE_HOOKS_DIR / 'zikra-error-capture.sh'
    ctx_hook = CLAUDE_HOOKS_DIR / 'zikra-context.sh'

    entries = [
        ('Stop',         str(hook_dst), ''),
        ('SessionEnd',   str(hook_dst), ''),
        ('PostToolUse',  str(err_hook), '[Ss]hell|[Bb]ash'),
        ('SessionStart', f'{ctx_hook} --plain', ''),
    ]

    kimi_dirs = []
    for d in (Path(os.getenv('KIMI_SHARE_DIR', Path.home() / '.kimi')),
              Path(os.getenv('KIMI_CODE_HOME', Path.home() / '.kimi-code'))):
        if d.exists():
            kimi_dirs.append(d)
    if not kimi_dirs:
        kimi_dirs = [Path.home() / '.kimi']  # fresh install: seed the legacy path

    for kimi_dir in kimi_dirs:
        kimi_dir.mkdir(parents=True, exist_ok=True)
        config_toml = kimi_dir / 'config.toml'
        content = config_toml.read_text() if config_toml.exists() else ''
        if 'kimi-hook.sh' in content:
            print(f'  ✓ Kimi hooks already present in {config_toml}')
            continue
        blocks = ['\n# Zikra memory-capture hooks (added by installer.py)']
        for event, command, matcher in entries:
            block = f'\n[[hooks]]\nevent = "{event}"\ncommand = "{command}"\n'
            if matcher:
                block += f'matcher = "{matcher}"\n'
            block += 'timeout = 30\n'
            blocks.append(block)
        config_toml.write_text(content + ''.join(blocks))
        print(f'  ✓ Kimi hooks registered in {config_toml}')


def install_gemini_hooks(cfg, _install_hook) -> None:
    """Legacy — Gemini CLI is no longer offered interactively (--with-gemini)."""
    gemini_dir = Path.home() / '.gemini'
    gemini_settings = gemini_dir / 'settings.json'
    hook_dst = CLAUDE_HOOKS_DIR / 'gemini-hook.sh'
    _install_hook('gemini-hook.sh', hook_dst)
    gemini_dir.mkdir(parents=True, exist_ok=True)
    try:
        gs = json.loads(gemini_settings.read_text()) if gemini_settings.exists() else {}
    except (json.JSONDecodeError, ValueError):
        gs = {}
    gs.setdefault('hooks', {})
    for event in ('AfterModel', 'SessionEnd'):
        entries = gs['hooks'].setdefault(event, [])
        entries[:] = [e for e in entries if e.get('name') != 'zikra']
        entries.append({'name': 'zikra', 'command': str(hook_dst)})
    tmp = str(gemini_settings) + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(gs, f, indent=2)
    os.replace(tmp, str(gemini_settings))
    print(f'  ✓ Gemini hooks registered in {gemini_settings}')


def install_shell_status(cfg, _install_hook) -> None:
    shell_status_dst = CLAUDE_HOOKS_DIR / 'zikra-shell-status.sh'
    _install_hook('zikra-shell-status.sh', shell_status_dst)
    source_line = f'source {shell_status_dst}'
    rc_files = []
    if os.environ.get('SHELL', '').endswith('zsh'):
        rc_files = [Path.home() / '.zshrc']
    else:
        rc_files = [Path.home() / '.bashrc']
    for rc in [Path.home() / '.bashrc', Path.home() / '.zshrc']:
        if rc.exists() and rc not in rc_files:
            rc_files.append(rc)
    for rc in rc_files:
        try:
            existing_rc = rc.read_text() if rc.exists() else ''
            if source_line not in existing_rc:
                with open(rc, 'a') as f:
                    f.write(f'\n# Zikra shell statusline (Codex / Kimi)\n{source_line}\n')
                print(f'  ✓ shell statusline added to {rc}')
            else:
                print(f'  ✓ {rc} already has the statusline source line')
        except OSError as e:
            print(f'  WARNING: Could not update {rc}: {e}')


def install_watcher(cfg, token) -> None:
    python_bin = sys.executable
    watcher_src = Path(__file__).parent / 'daemon' / 'zikra_watcher.py'
    watcher_dst = CLAUDE_DIR / 'zikra_watcher.py'
    watcher_content = watcher_src.read_text()
    watcher_content = watcher_content.replace('ZIKRA_TOKEN_PLACEHOLDER', token)
    watcher_content = watcher_content.replace(
        'ZIKRA_URL_PLACEHOLDER', f'http://{cfg["host"]}:{cfg["port"]}/webhook/zikra')
    watcher_content = watcher_content.replace('DEFAULT_PROJECT_PLACEHOLDER', cfg['project'])
    watcher_dst.write_text(watcher_content)
    watcher_dst.chmod(0o755)

    systemd_dir = Path.home() / '.config' / 'systemd' / 'user'
    service_content = f"""\
[Unit]
Description=Zikra Session Watcher Daemon
After=network.target

[Service]
ExecStart={python_bin} {watcher_dst}
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
"""
    if sys.platform.startswith('linux'):
        try:
            systemd_dir.mkdir(parents=True, exist_ok=True)
            (systemd_dir / 'zikra.service').write_text(service_content)
            print(f'  ✓ systemd unit written to {systemd_dir}/zikra.service')
            try:
                subprocess.run(['systemctl', '--user', 'daemon-reload'],
                               capture_output=True, timeout=10)
                r = subprocess.run(['systemctl', '--user', 'enable', '--now', 'zikra.service'],
                                   capture_output=True, text=True, timeout=15)
                if r.returncode == 0:
                    print('  ✓ zikra.service enabled and started')
                else:
                    print(f'  NOTE: enable manually: systemctl --user enable --now zikra.service')
            except Exception:
                print('  NOTE: enable manually: systemctl --user enable --now zikra.service')
        except OSError as e:
            print(f'  WARNING: Could not write systemd unit: {e}')
    else:
        print('  NOTE: systemd not available on this platform — skipping service install.')


def write_token_file(cfg, token) -> None:
    token_dir = Path.home() / '.zikra'
    token_dir.mkdir(parents=True, exist_ok=True)
    (token_dir / 'token').write_text(
        f'ZIKRA_TOKEN={token}\n'
        f'ZIKRA_URL=http://{cfg["host"]}:{cfg["port"]}/webhook/zikra\n'
        f'ZIKRA_PROJECT={cfg["project"]}\n'
    )
    print(f'  ✓ token saved to {token_dir}/token')


def wire_settings_json(cfg, token) -> None:
    settings_path = CLAUDE_DIR / 'settings.json'
    CLAUDE_DIR.mkdir(parents=True, exist_ok=True)
    if settings_path.exists():
        try:
            s = json.loads(settings_path.read_text())
        except (json.JSONDecodeError, ValueError):
            s = {}
    else:
        s = {}

    s.setdefault('mcpServers', {})
    mcp_host = 'localhost' if cfg['host'] in ('0.0.0.0', '') else cfg['host']
    runner_hostname = socket.gethostname() or 'unknown-host'
    s['mcpServers']['zikra'] = {
        'url': f'http://{mcp_host}:{cfg["port"]}/mcp',
        'headers': {
            'Authorization': f'Bearer {token}',
            'X-Zikra-Runner': runner_hostname,
        },
    }

    if cfg['profile'] in ('autolog', 'full'):
        autolog_path = str(CLAUDE_DIR / 'zikra_autolog.sh')
        stats_cmd = f'bash {CLAUDE_HOOKS_DIR / "zikra-stats-update.sh"}'
        context_path = str(CLAUDE_HOOKS_DIR / 'zikra-context.sh')
        errcap_path = str(CLAUDE_HOOKS_DIR / 'zikra-error-capture.sh')
        s['statusLine'] = {'type': 'command',
                           'command': 'node ~/.claude/hooks/zikra-statusline.js'}
        s.setdefault('hooks', {})

        def _matcher_cmds(m):
            return [h.get('command', '') for h in m.get('hooks', [])]

        def _strip_and_add(event, needles, additions):
            others = [m for m in s['hooks'].get(event, [])
                      if not any(any(n in c for n in needles) for c in _matcher_cmds(m))]
            s['hooks'][event] = others + additions

        _strip_and_add('Stop',
                       ['zikra_autolog.sh', 'zikra-stats-update.sh'],
                       [{'matcher': '', 'hooks': [{'type': 'command', 'command': autolog_path}]},
                        {'hooks': [{'type': 'command', 'command': stats_cmd, 'timeout': 10}]}])
        _strip_and_add('PreCompact',
                       ['zikra_autolog.sh'],
                       [{'matcher': '', 'hooks': [{'type': 'command', 'command': autolog_path}]}])
        # v1.1.0: auto-recall + error capture
        _strip_and_add('SessionStart',
                       ['zikra-context.sh'],
                       [{'matcher': '', 'hooks': [{'type': 'command', 'command': context_path, 'timeout': 10}]}])
        _strip_and_add('PostToolUse',
                       ['zikra-error-capture.sh'],
                       [{'matcher': 'Bash', 'hooks': [{'type': 'command', 'command': errcap_path, 'timeout': 10}]}])

    tmp = str(settings_path) + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(s, f, indent=2)
    os.replace(tmp, str(settings_path))
    print(f'  ✓ MCP server registered in {settings_path}')
    if cfg['profile'] in ('autolog', 'full'):
        print(f'  ✓ Stop/PreCompact/SessionStart/PostToolUse hooks + statusLine wired')


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    args = parse_args()

    if args.command == 'doctor':
        sys.path.insert(0, str(Path(__file__).parent))
        from zikra.doctor import run_doctor
        sys.exit(run_doctor(args.json))

    if args.non_interactive:
        cfg = gather_non_interactive(args)
    else:
        if not sys.stdin.isatty():
            print(
                'ERROR: interactive install needs a terminal.\n'
                'Use: python3 installer.py --non-interactive [--db sqlite|postgres] '
                '[--profile webhook|autolog|full] [--project NAME] [--with-codex] [--with-kimi]',
                file=sys.stderr)
            sys.exit(1)
        cfg = gather_interactive(args)

    token = secrets.token_urlsafe(32)

    if cfg['db_backend'] == 'sqlite' and cfg['host'] not in ('localhost', '127.0.0.1'):
        print()
        print('  ⚠  WARNING: SQLite is not recommended for team or remote deployments.')
        print('     SQLite is single-writer. Concurrent saves from multiple agents or')
        print('     machines may fail under load. Choose PostgreSQL for team use.')
        print()

    try:
        write_env(cfg, token)
    except OSError as e:
        print(f'ERROR: could not write .env: {e}', file=sys.stderr)
        sys.exit(1)

    if cfg['db_backend'] == 'postgres':
        try:
            import asyncpg  # noqa: F401
        except ImportError:
            print('ERROR: asyncpg is required for Postgres mode. Run: pip install asyncpg',
                  file=sys.stderr)
            sys.exit(1)

    _install_hook = make_hook_installer(cfg, token)

    if cfg['profile'] in ('autolog', 'full'):
        install_claude_hooks(cfg, _install_hook)
        write_projects_map(cfg)
        if cfg['install_codex']:
            install_codex_hooks(cfg, _install_hook)
        if cfg['install_kimi']:
            install_kimi_hooks(cfg, _install_hook)
        if cfg['install_gemini']:
            install_gemini_hooks(cfg, _install_hook)
        if cfg['install_codex'] or cfg['install_kimi'] or cfg['install_gemini']:
            install_shell_status(cfg, _install_hook)

    if cfg['profile'] == 'full':
        install_watcher(cfg, token)

    write_token_file(cfg, token)

    try:
        wire_settings_json(cfg, token)
    except Exception as e:
        print(f'  WARNING: Could not update settings.json: {e}')

    tool_list = ['Claude Code']
    if cfg['install_codex']:
        tool_list.append('Codex CLI')
    if cfg['install_kimi']:
        tool_list.append('Kimi CLI')
    if cfg['install_gemini']:
        tool_list.append('Gemini CLI (legacy)')

    distiller = 'enabled' if (cfg.get('llm_api_key') or cfg.get('openai_key')) else \
                'disabled (set ZIKRA_LLM_API_KEY or OPENAI_API_KEY in .env)'

    print(f"""
Zikra is ready.

  Token:           {token}
  Server:          http://{cfg['host']}:{cfg['port']}
  Profile:         {cfg['profile']}
  DB:              {cfg['db_backend']}
  Embedding model: {cfg.get('embedding_model', '')}
  Vector index:    {'halfvec HNSW (pgvector)' if cfg['db_backend'] == 'postgres' else 'brute-force (SQLite)'}
  Distiller:       {distiller}
  Integrated with: {', '.join(tool_list)}

  Start the server:
    python3 -m zikra --no-onboarding

  Health-check this install any time:
    python3 -m zikra doctor

  To reconfigure, delete .env and re-run installer.py
""")


if __name__ == '__main__':
    main()
