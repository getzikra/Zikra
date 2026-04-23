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
    'developer': ['create_token', 'get_schema', 'debug_protocol', 'delete_memory'],
    'viewer':    ['save_memory', 'save_prompt', 'save_requirement',
                  'promote_requirement', 'log_run', 'log_error',
                  'create_token', 'get_schema', 'debug_protocol',
                  'delete_memory'],
}


async def verify_auth(request: Request) -> dict:
    auth = request.headers.get('Authorization', '')
    if auth.startswith('Bearer '):
        token = auth[7:].strip()
    else:
        token = request.query_params.get('token', '').strip()
    if not token:
        raise HTTPException(status_code=401, detail='Unauthorized')

    # Reload env token each call so ZIKRA_TOKEN changes are picked up at runtime
    env_token = os.getenv('ZIKRA_TOKEN', ZIKRA_TOKEN)

    # Env token wins (backwards compat) — owner role, unrestricted scope
    if env_token and secrets.compare_digest(token.encode(), env_token.encode()):
        info = {'token': token, 'role': 'owner', 'label': 'owner', 'project_scope': None}
        try: request.state.token_label = 'owner'
        except Exception: pass
        return info

    # DB token lookup — branch on backend
    backend = os.getenv('DB_BACKEND', 'sqlite').lower()
    if backend == 'postgres':
        from zikra.db_postgres import get_pg_pool, verify_token_pg
        pool = get_pg_pool()
        if pool is None:
            raise HTTPException(status_code=503, detail='Database not ready')
        result = await verify_token_pg(pool, token)
        if not result:
            raise HTTPException(status_code=401, detail='Unauthorized')
        try: request.state.token_label = result['label']
        except Exception: pass
        return {
            'token': token,
            'role': result['role'],
            'label': result['label'],
            'project_scope': result.get('project_scope'),
        }

    # SQLite path
    db, lock = get_db_and_lock()
    if db is None:
        raise HTTPException(status_code=503, detail='Database not initialised')
    if lock is None:
        raise HTTPException(status_code=503, detail='Database not initialised')
    with lock:
        row = db.execute(
            'SELECT role, person_name, project_scope FROM access_tokens WHERE token = ? AND active = 1',
            [token]
        ).fetchone()

    if not row:
        raise HTTPException(status_code=401, detail='Unauthorized')

    label = row[1] or ''
    try: request.state.token_label = label
    except Exception: pass
    return {'token': token, 'role': row[0], 'label': label, 'project_scope': row[2]}


def assert_scope(auth_info: dict, project: str) -> None:
    """Raise 403 if the token is restricted to a different project."""
    scope = auth_info.get('project_scope')
    if scope and scope != project:
        raise HTTPException(
            status_code=403,
            detail={
                'error': 'token_scope_mismatch',
                'project_scope': scope,
                'requested_project': project,
                'message': (
                    f"This token is restricted to project '{scope}'. "
                    f"Set \"project\": \"{scope}\" in your request to continue."
                ),
                'hint': f'Change your project parameter to "{scope}".',
            }
        )
