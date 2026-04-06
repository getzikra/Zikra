import uuid
from zikra.db import add_token, new_id
from zikra.config import DEFAULT_TOKEN_ROLE


async def cmd_create_token(body: dict) -> dict:
    person_name = body.get('person_name', 'unknown')
    role = body.get('role', DEFAULT_TOKEN_ROLE)

    token = f"token-{uuid.uuid4().hex[:16]}"
    token_id = new_id()

    await add_token(token_id, token, person_name, role)

    return {
        'status': 'created',
        'token': token,
        'person_name': person_name,
        'role': role,
    }
