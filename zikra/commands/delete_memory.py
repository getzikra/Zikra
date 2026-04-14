from zikra.db import delete_memory, fetch_memory


async def cmd_delete_memory(body: dict) -> dict:
    memory_id = (body.get('id') or body.get('memory_id') or '').strip()
    title = (body.get('title') or '').strip()
    memory_type = body.get('memory_type')
    project = body.get('project') or None

    if not memory_id and not title:
        return {'error': 'id or title is required'}

    if not memory_id:
        row = await fetch_memory(title=title, memory_type=memory_type, project=project)
        if not row:
            return {'error': 'Memory not found'}
        memory_id = row['id']

    deleted = await delete_memory(memory_id)
    if not deleted:
        return {'error': 'Memory not found', 'id': memory_id}

    return {
        'deleted': True,
        'id': deleted['id'],
        'title': deleted.get('title'),
        'memory_type': deleted.get('memory_type'),
        'project': deleted.get('project'),
    }
