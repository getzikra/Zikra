from zikra.db import store_memory
from zikra.embed import embed


async def cmd_save_prompt(body: dict) -> dict:
    title = body.get('title', '')
    if not title:
        return {'error': 'title is required'}

    content = body.get('content_md') or body.get('content', '')
    body['memory_type'] = 'prompt'

    embedding = await embed(f'{title} {content}') or [0.0] * 1536

    memory_id = await store_memory(body, embedding)

    return {
        'id': memory_id,
        'title': title,
        'status': 'saved',
        'type': 'prompt',
    }
