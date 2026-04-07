from zikra.commands import _embed_and_store, _EMBED_WARNING


async def cmd_save_requirement(body: dict) -> dict:
    title = body.get('title', '')
    if not title:
        return {'error': 'title is required'}
    data = {**body, 'memory_type': 'requirement', 'pending_review': 1}
    req_id, degraded = await _embed_and_store(data, title)
    result = {'id': req_id, 'title': title, 'status': 'saved'}
    if degraded:
        result['warning'] = _EMBED_WARNING
    return result
