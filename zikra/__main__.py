import argparse
import logging
import os
import sys

from dotenv import load_dotenv


# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    # Parse args FIRST — before any .env loading.
    # This ensures --help works without a .env.
    parser = argparse.ArgumentParser(description='Zikra — local MCP memory server')
    parser.add_argument('--host', default=None,
                        help='Host to bind (default: value of ZIKRA_HOST or 0.0.0.0)')
    parser.add_argument('--port', type=int, default=None,
                        help='Port to listen on (default: value of ZIKRA_PORT or 8000)')
    parser.add_argument('--no-onboarding', action='store_true',
                        help='Skip interactive onboarding wizard on startup')
    args = parser.parse_args()

    if args.no_onboarding:
        os.environ['ZIKRA_SKIP_ONBOARDING'] = '1'

    # If no .env and not suppressed, tell user to run installer
    skip_message = (
        os.environ.get('ZIKRA_SKIP_ONBOARDING') == '1'
    )

    if not os.path.exists('.env') and not skip_message:
        print('No .env found. Run: python3 installer.py', file=sys.stderr)
        sys.exit(1)

    load_dotenv()

    host = args.host or os.getenv('ZIKRA_HOST', '0.0.0.0')
    port = args.port or int(os.getenv('ZIKRA_PORT', '8000'))

    backend = os.getenv('DB_BACKEND', 'sqlite').lower()

    VALID_BACKENDS = ('sqlite', 'postgres')
    if backend not in VALID_BACKENDS:
        print(
            f"ERROR: DB_BACKEND={backend!r} is not valid. "
            f"Use one of: {', '.join(VALID_BACKENDS)}",
            file=sys.stderr
        )
        sys.exit(1)

    # Give the root logger a handler so zikra.* INFO messages reach the console.
    # uvicorn loggers have propagate=False, so no double-printing occurs.
    logging.basicConfig(level=logging.INFO, format='%(levelname)s:     %(message)s')

    if backend == 'postgres':
        import uvicorn
        uvicorn.run('zikra.server:app', host=host, port=port, reload=False,
                    log_level='info')
        return

    # SQLite path
    from zikra.db import _make_connection
    from zikra.migrate import run_migrations
    from zikra.onboarding import run_onboarding

    path = os.getenv('ZIKRA_DB_PATH', './zikra.db')
    conn = _make_connection(path)
    run_migrations(conn)

    run_onboarding(conn, port=port)
    conn.close()

    import uvicorn
    uvicorn.run('zikra.server:app', host=host, port=port, reload=False,
                log_level='info')


if __name__ == '__main__':
    main()
