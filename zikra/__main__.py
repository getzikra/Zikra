import argparse
import filecmp
import logging
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

from dotenv import load_dotenv


# ── Update check (background, fail-silent) ────────────────────────────────────

def _check_for_updates():
    """Spawn a daemon thread that compares local git SHA to GitHub HEAD."""
    def _check():
        try:
            import json
            import urllib.request

            req = urllib.request.Request(
                'https://api.github.com/repos/getzikra/zikra/commits/main',
                headers={'User-Agent': 'zikra-update-check/1.0'},
            )
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read())
            remote_sha = data['sha'][:7]

            # Try git rev-parse first, fall back to reading .git/refs directly
            install_dir = Path(__file__).parent.parent
            try:
                result = subprocess.run(
                    ['git', 'rev-parse', 'HEAD'],
                    cwd=install_dir, capture_output=True, text=True, timeout=2,
                )
                local_sha = result.stdout.strip()[:7]
            except Exception:
                ref_file = install_dir / '.git' / 'refs' / 'heads' / 'main'
                local_sha = ref_file.read_text().strip()[:7] if ref_file.exists() else None

            if local_sha and remote_sha != local_sha:
                print(f'\n\u26a0  Zikra update available \u2014 run: zikra update\n', flush=True)
        except Exception:
            pass  # unreachable host, not a git repo, etc. — fail silently

    t = threading.Thread(target=_check, daemon=True)
    t.start()


# ── Update subcommand ─────────────────────────────────────────────────────────

def run_update():
    """Pull latest from GitHub, refresh pip install, update hooks."""
    install_dir = Path(__file__).parent.parent
    hooks_dir = install_dir / 'hooks'
    claude_dir = Path.home() / '.claude'
    token_file = Path.home() / '.zikra' / 'token'

    print('Updating Zikra...\n')

    # 1 — git pull
    try:
        result = subprocess.run(
            ['git', 'pull', 'origin', 'main'],
            cwd=install_dir, capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip())
        print(result.stdout.strip() or 'Already up to date.')
    except Exception as e:
        print(f'Cannot update \u2014 not installed via git.')
        print(f'Download latest from https://github.com/getzikra/zikra')
        print(f'({e})')
        sys.exit(1)

    # 2 — pip install
    load_dotenv(install_dir / '.env')
    backend = os.getenv('DB_BACKEND', 'sqlite').lower()
    pip_arg = '-e .[postgres]' if backend == 'postgres' else '-e .'
    pip_result = subprocess.run(
        [sys.executable, '-m', 'pip', 'install'] + pip_arg.split(),
        cwd=install_dir, capture_output=True, text=True,
    )
    if pip_result.returncode != 0:
        print(f'pip install warning: {pip_result.stderr[-300:]}')
    else:
        print(f'pip: {pip_arg} installed OK')

    # 3 — new sha
    try:
        sha_result = subprocess.run(
            ['git', 'rev-parse', 'HEAD'],
            cwd=install_dir, capture_output=True, text=True,
        )
        new_sha = sha_result.stdout.strip()[:7]
    except Exception:
        new_sha = 'unknown'

    # 4 — update hooks in ~/.claude/ that differ from repo hooks/
    updated_hooks = []
    if hooks_dir.exists() and token_file.exists():
        creds: dict = {}
        for line in token_file.read_text().splitlines():
            if '=' in line:
                k, _, v = line.partition('=')
                creds[k.strip()] = v.strip()

        backup_dir = claude_dir / 'zikra_backups'
        backup_dir.mkdir(parents=True, exist_ok=True)

        for hook_file in sorted(hooks_dir.iterdir()):
            if hook_file.name.startswith('__') or hook_file.suffix == '.pyc':
                continue
            dest = claude_dir / hook_file.name
            if not dest.exists():
                continue
            if not filecmp.cmp(str(hook_file), str(dest), shallow=False):
                shutil.copy2(str(dest), str(backup_dir / (hook_file.name + '.bak')))
                content = hook_file.read_text()
                content = content.replace('ZIKRA_URL_PLACEHOLDER',
                                          creds.get('ZIKRA_URL', ''))
                content = content.replace('ZIKRA_TOKEN_PLACEHOLDER',
                                          creds.get('ZIKRA_TOKEN', ''))
                content = content.replace('DEFAULT_PROJECT_PLACEHOLDER',
                                          creds.get('ZIKRA_PROJECT', 'global'))
                dest.write_text(content)
                print(f'  \u2713 updated ~/.claude/{hook_file.name}')
                updated_hooks.append(hook_file.name)

    # 5 — Docker: print rebuild instructions, do not rebuild automatically
    in_docker = Path('/.dockerenv').exists()
    restart_status = ''
    if in_docker:
        print('\nRunning inside Docker \u2014 to apply update:')
        print('  docker compose -f docker-compose.local.yml up -d --build')
        restart_status = 'manual step required'
    else:
        # 6 — systemd: restart if the service is active
        try:
            check = subprocess.run(
                ['systemctl', '--user', 'is-active', 'zikra'],
                capture_output=True, text=True, timeout=5,
            )
            if check.stdout.strip() == 'active':
                subprocess.run(
                    ['systemctl', '--user', 'restart', 'zikra'], check=True, timeout=10,
                )
                restart_status = 'done (systemd restarted)'
            else:
                restart_status = 'not running as systemd service'
        except Exception:
            restart_status = 'not running as systemd service'

    # 7 — summary
    print(f'\nZikra updated to {new_sha}')
    print(f'Hooks updated:   {", ".join(updated_hooks) if updated_hooks else "none"}')
    print(f'Restart:         {restart_status}')


# ── Server entry point ────────────────────────────────────────────────────────

def main():
    # Handle `zikra update` before argparse so the server flags don't interfere
    if len(sys.argv) > 1 and sys.argv[1] == 'update':
        run_update()
        return

    parser = argparse.ArgumentParser(description='Zikra \u2014 local MCP memory server')
    parser.add_argument('--host', default=None,
                        help='Host to bind (default: ZIKRA_HOST or 0.0.0.0)')
    parser.add_argument('--port', type=int, default=None,
                        help='Port to listen on (default: ZIKRA_PORT or 8000)')
    parser.add_argument('--no-onboarding', action='store_true',
                        help='Skip interactive onboarding wizard on startup')
    args = parser.parse_args()

    if args.no_onboarding:
        os.environ['ZIKRA_SKIP_ONBOARDING'] = '1'

    if not os.path.exists('.env') and os.environ.get('ZIKRA_SKIP_ONBOARDING') != '1':
        print('No .env found. Run: python3 installer.py', file=sys.stderr)
        sys.exit(1)

    load_dotenv()

    # Warn if env-token auth is disabled
    if not os.getenv('ZIKRA_TOKEN', '').strip():
        print(
            'WARNING: ZIKRA_TOKEN is empty \u2014 all auth will fall through to DB token lookup. '
            'Set ZIKRA_TOKEN in .env to enable env-token auth.',
            file=sys.stderr,
        )

    host = args.host or os.getenv('ZIKRA_HOST', '0.0.0.0')
    port = args.port or int(os.getenv('ZIKRA_PORT', '8000'))
    backend = os.getenv('DB_BACKEND', 'sqlite').lower()

    if backend not in ('sqlite', 'postgres'):
        print(
            f'ERROR: DB_BACKEND={backend!r} is not valid. Use: sqlite or postgres',
            file=sys.stderr,
        )
        sys.exit(1)

    logging.basicConfig(level=logging.INFO, format='%(levelname)s:     %(message)s')

    # SQLite: run migrations + onboarding once before uvicorn starts.
    # init_db() is idempotent — the server's lifespan will call it again and skip.
    if backend == 'sqlite':
        from zikra.db import init_db
        from zikra.onboarding import run_onboarding
        db, _ = init_db()
        run_onboarding(db, port=port)

    # Background update check — non-blocking, fail-silent
    _check_for_updates()

    import uvicorn
    uvicorn.run('zikra.server:app', host=host, port=port, reload=False, log_level='info')


if __name__ == '__main__':
    main()
