from zikra.db import store_memory
from zikra.embed import embed


async def cmd_save_requirement(body: dict) -> dict:
    title = body.get('title', '')
    if not title:
        return {'error': 'title is required'}

    data = {**body, 'memory_type': 'requirement', 'pending_review': 1}
    content = data.get('content_md') or data.get('content', '')
    embedding = await embed(f'{title} {content}') or [0.0] * 1536

    req_id = await store_memory(data, embedding)

    return {
        'id': req_id,
        'title': title,
        'status': 'saved',
    }
