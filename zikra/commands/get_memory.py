import json
from zikra.db import fetch_memory
from zikra.commands import _require_project


async def cmd_get_memory(body: dict) -> dict:
    title = body.get('title', '')
    memory_id = body.get('id', '')
    memory_type = body.get('memory_type')
    project = _require_project(body)

    if not title and not memory_id:
        return {'error': 'title or id is required'}

    row = await fetch_memory(memory_id=memory_id or None,
                             title=title or None,
                             memory_type=memory_type,
                             project=project)

    if not row:
        return {'error': 'Memory not found'}

    tags = row['tags']
    if isinstance(tags, str):
        try:
            tags = json.loads(tags or '[]')
        except (json.JSONDecodeError, ValueError):
            tags = []

    return {
        'id': row['id'],
        'title': row['title'],
        'content_md': row['content_md'],
        'memory_type': row['memory_type'],
        'project': row['project'],
        'module': row['module'],
        'tags': tags,
        'resolution': row['resolution'],
        'access_count': row['access_count'],
        'created_at': row['created_at'],
        'updated_at': row['updated_at'],
    }
