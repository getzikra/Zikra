import uuid
from zikra.db import add_token, new_id
from zikra.auth import ROLE_PERMISSIONS
from zikra.config import DEFAULT_TOKEN_ROLE

# owner cannot be granted via API — only the env token holds owner rights
GRANTABLE_ROLES = set(ROLE_PERMISSIONS.keys()) - {'owner'}


async def cmd_create_token(body: dict) -> dict:
    label         = body.get('label') or body.get('person_name', 'unknown')
    role          = body.get('role', DEFAULT_TOKEN_ROLE)
    project_scope = body.get('project_scope') or None

    if role not in GRANTABLE_ROLES:
        return {
            'error': f"Invalid role {role!r}.",
            'allowed_roles': sorted(GRANTABLE_ROLES),
        }

    token    = f"token-{uuid.uuid4().hex[:16]}"
    token_id = new_id()

    await add_token(token_id, token, label, role, project_scope)

    return {
        'status': 'created',
        'token': token,
        'label': label,
        'person_name': label,
        'role': role,
        'project_scope': project_scope,
    }
