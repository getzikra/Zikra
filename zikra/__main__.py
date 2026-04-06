import argparse
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
                        help='No-op flag kept for backwards compatibility')
    args = parser.parse_args()

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

    if backend == 'postgres':
        print(f'Zikra running at http://{host}:{port}/webhook/zikra (backend: postgres)')
        import uvicorn
        uvicorn.run('zikra.server:app', host=host, port=port, reload=False)
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

    print(f'Zikra running at http://{host}:{port}/webhook/zikra (backend: sqlite)')
    import uvicorn
    uvicorn.run('zikra.server:app', host=host, port=port, reload=False)


if __name__ == '__main__':
    main()
