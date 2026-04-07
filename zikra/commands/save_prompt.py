from zikra.commands import _embed_and_store, _EMBED_WARNING


async def cmd_save_prompt(body: dict) -> dict:
    title = body.get('title', '')
    if not title:
        return {'error': 'title is required'}
    memory_id, degraded = await _embed_and_store({**body, 'memory_type': 'prompt'}, title)
    result = {'id': memory_id, 'title': title, 'status': 'saved', 'type': 'prompt'}
    if degraded:
        result['warning'] = _EMBED_WARNING
    return result
