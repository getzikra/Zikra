from zikra.db import store_memory
from zikra.embed import embed


async def cmd_save_prompt(body: dict) -> dict:
    title = body.get('title', '')
    if not title:
        return {'error': 'title is required'}

    content = body.get('content_md') or body.get('content', '')
    body['memory_type'] = 'prompt'

    _raw_embed = await embed(f'{title} {content}')
    embedding = _raw_embed if _raw_embed is not None else [0.0] * 1536
    embedding_degraded = _raw_embed is None

    memory_id = await store_memory(body, embedding)

    result = {'id': memory_id, 'title': title, 'status': 'saved', 'type': 'prompt'}
    if embedding_degraded:
        result['warning'] = 'semantic embedding unavailable; keyword search only for this entry'
    return result
