from zikra.db import change_memory_type, fetch_memory


async def cmd_promote_requirement(body: dict) -> dict:
    req_id = body.get('id') or body.get('requirement_id')
    title  = body.get('title')

    if not req_id and not title:
        return {'error': 'id, requirement_id, or title is required'}

    if not req_id:
        found = await fetch_memory(title=title)
        if not found or found.get('memory_type') != 'requirement':
            return {'error': f'Requirement with title "{title}" not found'}
        req_id = found['id']

    promote_to = body.get('promote_to', 'prompt')
    row = await change_memory_type(req_id, promote_to)

    if not row:
        return {'error': 'Requirement not found or already promoted'}

    return {
        'status': 'promoted',
        'id': row['id'],
        'title': row['title'],
    }
