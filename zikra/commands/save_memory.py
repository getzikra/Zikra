from zikra.db import store_memory
from zikra.embed import embed


async def cmd_save_memory(body: dict) -> dict:
    title = body.get('title', '')
    if not title:
        return {'error': 'title is required'}

    content = body.get('content_md') or body.get('content', '')
    embedding = await embed(f'{title} {content}') or [0.0] * 1536

    memory_id = await store_memory(body, embedding)

    return {
        'id': memory_id,
        'title': title,
        'status': 'saved',
    }
