#!/usr/bin/env python3
"""
Zikra unified installer.
Run: python3 installer.py
"""

import sys
import os

if not sys.stdin.isatty():
    print(
        "ERROR: Zikra installer requires an interactive terminal.\n"
        "Run: python3 installer.py\n"
        "Or pre-set all vars in a .env file and run: python3 -m zikra --no-onboarding",
        file=sys.stderr
    )
    sys.exit(1)

import json
import re
import secrets
from pathlib import Path


# ── Question helpers ──────────────────────────────────────────────────────────

def _ask(prompt, default=None, validate=None):
    """Prompt user, return validated answer (or default on empty)."""
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


# ── Question flow ─────────────────────────────────────────────────────────────

print()
print('╔═══════════════════════════════════════╗')
print('║         Zikra Installer               ║')
print('║   Persistent memory for AI agents     ║')
print('╚═══════════════════════════════════════╝')
print()

# Q1 — Storage backend
print('Where should Zikra store data?')
print('  [1] SQLite — local file, zero setup (recommended for personal use)')
print('  [2] PostgreSQL — external database (recommended for teams)')
db_choice = _ask_choice('  Choice', ['1', '2'], default='1')
db_backend = 'postgres' if db_choice == '2' else 'sqlite'

pg_host = ''
pg_port = '5432'
pg_name = ''
pg_user = ''
pg_password = ''

if db_backend == 'postgres':
    print()
    pg_host     = _ask('  Postgres host', default='localhost')
    pg_port     = _ask('  Postgres port', default='5432',
                       validate=lambda v: 'Must be a valid port number' if not v.isdigit() else None)
    pg_name     = _ask('  Postgres database name')
    pg_user     = _ask('  Postgres user')
    pg_password = _ask('  Postgres password')

# Q2 — Hook depth
print()
print('How deeply should Zikra integrate with Claude Code?')
print('  [1] Webhook only — just the API, no file hooks')
print('  [2] Auto-log — installs shell hooks that log sessions automatically')
print('  [3] Full — auto-log + background watcher daemon + systemd service')
hook_choice = _ask_choice('  Choice', ['1', '2', '3'], default='1')
zikra_profile = {'1': 'webhook', '2': 'autolog', '3': 'full'}[hook_choice]

if db_backend == 'postgres':
    default_model = 'text-embedding-3-large'
else:
    default_model = 'text-embedding-3-small'

# Q3 — OpenAI API key
print()
print('Do you have an OpenAI API key for semantic search? (leave blank to skip)')
openai_key = _ask('  Key', default='',
                  validate=lambda v: None if not v or (v.startswith('sk-') and len(v) >= 8) else
                           "Must start with 'sk-' or leave blank to skip")
if not openai_key:
    print('  WARNING: Running in keyword-only mode. '
          'Add OPENAI_API_KEY to .env later to enable semantic search.')
elif db_backend == 'sqlite':
    print('  NOTE: SQLite uses brute-force vector search (no ANN index).')
    print('  text-embedding-3-small recommended. Switch to Postgres for team use.')

# Q4 — Project name
print()
def _validate_project(v):
    if not v:
        return 'Project name cannot be empty'
    if not re.match(r'^[a-z0-9][a-z0-9\-]*$', v):
        return 'Only lowercase letters, numbers, and hyphens allowed. No spaces or uppercase.'
    return None

project = _ask('  Default project name for this installation', default='main',
               validate=_validate_project)

# ── Generate token and write .env ─────────────────────────────────────────────

print()
zikra_host = _ask(' Zikra bind host', default='0.0.0.0')
zikra_port = _ask(' Zikra server port', default='8000',
    validate=lambda v: 'Must be a valid port number' if not v.isdigit() else None)

token = secrets.token_urlsafe(32)

# ── Warn about SQLite under team/remote deployments ───────────────────────────
if db_backend == 'sqlite' and zikra_host not in ('localhost', '127.0.0.1'):
    print()
    print('  ⚠  WARNING: SQLite is not recommended for team or remote deployments.')
    print('     SQLite is single-writer. Concurrent saves from multiple agents or')
    print('     machines may fail under load.')
    print('     Re-run the installer and choose PostgreSQL (option 2) for team use.')
    print()

env_lines = [
    f'ZIKRA_TOKEN={token}',
    'ZIKRA_SKIP_ONBOARDING=1',
    f'OPENAI_API_KEY={openai_key}',
    f'ZIKRA_EMBEDDING_MODEL={default_model}',
    f'DB_BACKEND={db_backend}',
]

if db_backend == 'postgres':
    env_lines += [
        f'DB_HOST={pg_host}',
        f'DB_PORT={pg_port}',
        f'DB_NAME={pg_name}',
        f'DB_USER={pg_user}',
        f'DB_PASSWORD={pg_password}',
    ]

env_lines += [
    f'ZIKRA_HOST={zikra_host}',
    f'ZIKRA_PORT={zikra_port}',
    f'ZIKRA_PROJECT={project}',
]

env_content = '\n'.join(env_lines) + '\n'
try:
    Path('.env').write_text(env_content)
    print('✓ .env written')
except OSError as e:
    print(f'ERROR: could not write .env: {e}', file=sys.stderr)
    sys.exit(1)

# ── Postgres: verify asyncpg is available ────────────────────────────────────

if db_backend == 'postgres':
    try:
        import asyncpg  # noqa: F401
    except ImportError:
        print('ERROR: asyncpg is required for Postgres mode. Run: pip install asyncpg',
              file=sys.stderr)
        sys.exit(1)

# ── Install hooks ─────────────────────────────────────────────────────────────

HOOKS_SRC = Path(__file__).parent / 'hooks'
CLAUDE_DIR = Path.home() / '.claude'
CLAUDE_HOOKS_DIR = CLAUDE_DIR / 'hooks'

if zikra_profile in ('autolog', 'full'):
    CLAUDE_DIR.mkdir(parents=True, exist_ok=True)
    CLAUDE_HOOKS_DIR.mkdir(parents=True, exist_ok=True)

    def _install_hook(src_name, dst_path):
        src = HOOKS_SRC / src_name
        content = src.read_text()
        content = content.replace('ZIKRA_TOKEN_PLACEHOLDER', token)
        content = content.replace('ZIKRA_URL_PLACEHOLDER', f'http://{zikra_host}:{zikra_port}/webhook/zikra')
        content = content.replace('ZIKRA_PROJECT_PLACEHOLDER', project)
        content = content.replace('DEFAULT_PROJECT_PLACEHOLDER', project)
        dst_path.write_text(content)
        dst_path.chmod(0o755)
        print(f'  ✓ installed {dst_path}')

    _install_hook('zikra_autolog.sh', CLAUDE_DIR / 'zikra_autolog.sh')
    _install_hook('notify.sh', CLAUDE_DIR / 'notify.sh')
    _install_hook('zikra-statusline.js', CLAUDE_HOOKS_DIR / 'zikra-statusline.js')

# ── Full profile: systemd unit ────────────────────────────────────────────────

if zikra_profile == 'full':
    python_bin = sys.executable
    watcher_src = Path(__file__).parent / 'daemon' / 'zikra_watcher.py'
    watcher_dst = CLAUDE_DIR / 'zikra_watcher.py'

    # Copy watcher with placeholders replaced
    watcher_content = watcher_src.read_text()
    watcher_content = watcher_content.replace('ZIKRA_TOKEN_PLACEHOLDER', token)
    watcher_content = watcher_content.replace(
        'ZIKRA_URL_PLACEHOLDER', f'http://{zikra_host}:{zikra_port}/webhook/zikra')
    watcher_content = watcher_content.replace('DEFAULT_PROJECT_PLACEHOLDER', project)
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
        except OSError as e:
            print(f'  WARNING: Could not write systemd unit: {e}')
    else:
        print('  NOTE: systemd not available on this platform — skipping service install.')

# ── Save token to ~/.zikra/token ──────────────────────────────────────────────

token_dir = Path.home() / '.zikra'
try:
    token_dir.mkdir(parents=True, exist_ok=True)
    (token_dir / 'token').write_text(
        f'ZIKRA_TOKEN={token}\n'
        f'ZIKRA_URL=http://{zikra_host}:{zikra_port}/webhook/zikra\n'
        f'ZIKRA_PROJECT={project}\n'
    )
    print(f'  ✓ token saved to {token_dir}/token')
except OSError as e:
    print(f'  WARNING: Could not save token file: {e}')

# ── Register MCP server in ~/.claude/settings.json ───────────────────────────

settings_path = CLAUDE_DIR / 'settings.json'
try:
    CLAUDE_DIR.mkdir(parents=True, exist_ok=True)
    if settings_path.exists():
        try:
            s = json.loads(settings_path.read_text())
        except (json.JSONDecodeError, ValueError):
            s = {}
    else:
        s = {}

    s.setdefault('mcpServers', {})
    mcp_host = 'localhost' if zikra_host in ('0.0.0.0', '') else zikra_host
    s['mcpServers']['zikra'] = {
        'url': f'http://{mcp_host}:{zikra_port}/mcp',
        'headers': {'Authorization': f'Bearer {token}'},
    }

    tmp = str(settings_path) + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(s, f, indent=2)
    os.replace(tmp, str(settings_path))
    print(f'  ✓ MCP server registered in {settings_path}')
except Exception as e:
    print(f'  WARNING: Could not update settings.json: {e}')

# ── Summary ───────────────────────────────────────────────────────────────────

print(f"""
Zikra is ready.

  Token:           {token}
  Server:          http://{zikra_host}:{zikra_port}
  Profile:         {zikra_profile}
  DB:              {db_backend}
  Embedding model: {default_model}
  Vector index:    {'halfvec HNSW (pgvector)' if db_backend == 'postgres' else 'brute-force (SQLite)'}

  Add this to your Claude Code MCP config if not already done:
  {{
    "zikra": {{
      "url": "http://localhost:{zikra_port}/mcp"
    }}
  }}

  Onboarding prompt: prompts/zikra-cli-install-update.md
  Run in Claude Code: /prompts then select zikra-cli-install-update
  Or: cat prompts/zikra-cli-install-update.md | pbcopy  (then paste into Claude Code)

  Start the server:
    python3 -m zikra --no-onboarding

  To reconfigure, delete .env and re-run installer.py
""")
