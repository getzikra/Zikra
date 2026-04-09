import re
import secrets
import sqlite3
import uuid
import os
from pathlib import Path


BANNER = """
╔══════════════════════════════════════════╗
║              Welcome to Zikra             ║
║   Your local AI memory and prompt store  ║
╚══════════════════════════════════════════╝
"""


def _ask(prompt: str, validator=None, default: str = None) -> str:
    while True:
        suffix = f' [{default}]' if default else ''
        raw = input(f'{prompt}{suffix}: ').strip()
        if not raw and default:
            return default
        if not raw:
            print('  Required — please enter a value.')
            continue
        if validator:
            err = validator(raw)
            if err:
                print(f'  {err}')
                continue
        return raw


def _validate_name(v: str):
    if ' ' in v:
        return 'No spaces allowed.'
    return None


def _validate_token_name(v: str):
    if not re.match(r'^[a-z0-9][a-z0-9\-]*$', v):
        return 'Lowercase letters, digits, and hyphens only. Must start with a letter or digit.'
    return None


def _validate_project(v: str):
    if v != v.lower():
        return 'Lowercase only.'
    return None


def run_onboarding(conn: sqlite3.Connection, port: int = 8000):
    import sys, os
    if os.getenv('ZIKRA_SKIP_ONBOARDING') or not sys.stdin or not sys.stdin.isatty():
        return

    # Step 6: Skip if any token already exists
    row = conn.execute('SELECT COUNT(*) FROM access_tokens').fetchone()
    if row[0] > 0:
        return

    # Step 1: Seed global project memory
    memory_id = str(uuid.uuid4())
    conn.execute("""
        INSERT INTO memories (id, project, memory_type, title, content_md, created_by)
        VALUES (?, 'global', 'decision', 'zikra initialized',
                'Zikra installed and running. Global project created.', 'system')
        ON CONFLICT(title, memory_type, project) DO NOTHING
    """, [memory_id])
    seed_row = conn.execute(
        "SELECT rowid FROM memories WHERE title='zikra initialized' AND memory_type='decision'"
    ).fetchone()
    if seed_row:
        conn.execute(
            'INSERT OR REPLACE INTO memories_fts(rowid, title, content_md) VALUES (?, ?, ?)',
            [seed_row[0], 'zikra initialized',
             'Zikra installed and running. Global project created.']
        )
    conn.commit()

    # Step 2: Ask 3 questions
    print(BANNER)
    print('Setting up your Zikra install. Answer 3 quick questions.\n')

    person_name = _ask('Your name (no spaces)', _validate_name)
    token_name = _ask('Token name (e.g. my-laptop)', _validate_token_name)
    user_project = _ask('Default project (leave blank for global)',
                        _validate_project, default='global')

    # Step 3: Generate token and save to DB
    token = 'zikra-' + secrets.token_hex(8)
    token_id = str(uuid.uuid4())
    conn.execute("""
        INSERT INTO access_tokens (id, token, person_name, token_name, role, active)
        VALUES (?, ?, ?, ?, 'admin', 1)
    """, [token_id, token, person_name, token_name])
    conn.commit()

    zikra_url = f'http://localhost:{port}/webhook/zikra'

    # Step 5: Save token file
    token_dir = Path.home() / '.zikra'
    token_dir.mkdir(parents=True, exist_ok=True)
    token_file = token_dir / 'token'
    token_file.write_text(
        f'ZIKRA_TOKEN={token}\n'
        f'ZIKRA_URL={zikra_url}\n'
        f'ZIKRA_PROJECT={user_project}\n'
    )
    token_file.chmod(0o600)

    # Step 4: Print Claude Code config
    print('\n' + '=' * 60)
    print('  Zikra is ready!')
    print('=' * 60)
    print(f'\n  Token:   {token}')
    print(f'  Project: {user_project}')
    print(f'  URL:     {zikra_url}')
    print(f'\n  Token saved to: {token_file}')
    print('\n' + '-' * 60)
    print('  Connect Claude Code to Zikra:')
    print('-' * 60)
    print(f"""
  Fetch https://raw.githubusercontent.com/getzikra/zikra/main/prompts/zikra-cli-install-update.md
  and follow every instruction in it.

  When it asks for your Zikra URL enter:  {zikra_url}
  When it asks for your token enter:      {token}
  When it asks for your project enter:    {user_project}
""")
    print('=' * 60 + '\n')
