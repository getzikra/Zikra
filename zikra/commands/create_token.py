import uuid
from zikra.db import add_token, new_id
from zikra.config import DEFAULT_TOKEN_ROLE


async def cmd_create_token(body: dict) -> dict:
    label = body.get('label') or body.get('person_name', 'unknown')
    role = body.get('role', DEFAULT_TOKEN_ROLE)

    token = f"token-{uuid.uuid4().hex[:16]}"
    token_id = new_id()

    await add_token(token_id, token, label, role)

    return {
        'status': 'created',
        'token': token,
        'label': label,
        'person_name': label,
        'role': role,
    }
