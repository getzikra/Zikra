import argparse
import logging
import os
import sys

from dotenv import load_dotenv


def main():
    parser = argparse.ArgumentParser(description='Zikra — local MCP memory server')
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
            'WARNING: ZIKRA_TOKEN is empty — all auth will fall through to DB token lookup. '
            'Set ZIKRA_TOKEN in .env to enable env-token auth.',
            file=sys.stderr,
        )

    host = args.host or os.getenv('ZIKRA_HOST', '0.0.0.0')
    port = args.port or int(os.getenv('ZIKRA_PORT', '8000'))
    backend = os.getenv('DB_BACKEND', 'sqlite').lower()

    if backend not in ('sqlite', 'postgres'):
        print(
            f"ERROR: DB_BACKEND={backend!r} is not valid. Use: sqlite or postgres",
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

    import uvicorn
    uvicorn.run('zikra.server:app', host=host, port=port, reload=False, log_level='info')


if __name__ == '__main__':
    main()
