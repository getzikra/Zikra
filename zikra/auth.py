"""
auth.py — shared auth utilities for server.py and mcp_server.py.
Extracted to break the server <-> mcp_server circular import.
"""
import os
import secrets
from fastapi import HTTPException, Request

from zikra.db import get_db_and_lock

ZIKRA_TOKEN = os.getenv('ZIKRA_TOKEN', '')

ROLE_PERMISSIONS = {
    'owner':     [],  # empty blocked list = all commands allowed
    'admin':     ['create_token'],
    'developer': ['create_token', 'get_schema', 'debug_protocol'],
    'viewer':    ['save_memory', 'save_prompt', 'save_requirement',
                  'promote_requirement', 'log_run', 'log_error',
                  'create_token', 'get_schema', 'debug_protocol'],
}


async def verify_auth(request: Request) -> dict:
    auth = request.headers.get('Authorization', '')
    if not auth.startswith('Bearer '):
        raise HTTPException(status_code=401, detail='Unauthorized')
    token = auth[7:].strip()
    if not token:
        raise HTTPException(status_code=401, detail='Unauthorized')

    # Reload env token each call so ZIKRA_TOKEN changes are picked up at runtime
    env_token = os.getenv('ZIKRA_TOKEN', ZIKRA_TOKEN)

    # Env token wins (backwards compat) — owner role
    if env_token and secrets.compare_digest(token.encode(), env_token.encode()):
        return {'token': token, 'role': 'owner'}

    # DB token lookup — branch on backend
    backend = os.getenv('DB_BACKEND', 'sqlite').lower()
    if backend == 'postgres':
        from zikra.db_postgres import get_pg_pool, verify_token_pg
        pool = get_pg_pool()
        if pool is None:
            raise HTTPException(status_code=503, detail='Database not ready')
        role = await verify_token_pg(pool, token)
        if not role:
            raise HTTPException(status_code=401, detail='Unauthorized')
        return {'token': token, 'role': role}

    # SQLite path
    db, lock = get_db_and_lock()
    if db is None:
        raise HTTPException(status_code=503, detail='Database not initialised')
    if lock is None:
        raise HTTPException(status_code=503, detail='Database not initialised')
    with lock:
        row = db.execute(
            'SELECT role FROM access_tokens WHERE token = ? AND active = 1',
            [token]
        ).fetchone()

    if not row:
        raise HTTPException(status_code=401, detail='Unauthorized')

    return {'token': token, 'role': row[0]}
