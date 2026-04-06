from zikra.db import store_memory
from zikra.embed import embed


async def cmd_save_requirement(body: dict) -> dict:
    title = body.get('title', '')
    if not title:
        return {'error': 'title is required'}

    data = {**body, 'memory_type': 'requirement', 'pending_review': 1}
    content = data.get('content_md') or data.get('content', '')
    _raw_embed = await embed(f'{title} {content}')
    embedding = _raw_embed if _raw_embed is not None else [0.0] * 1536
    embedding_degraded = _raw_embed is None

    req_id = await store_memory(data, embedding)

    result = {'id': req_id, 'title': title, 'status': 'saved'}
    if embedding_degraded:
        result['warning'] = 'semantic embedding unavailable; keyword search only for this entry'
    return result
