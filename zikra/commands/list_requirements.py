from fastapi import HTTPException

from zikra.db import list_by_memory_type


async def cmd_list_requirements(body: dict) -> dict:
    project = body.get('project', 'global')
    try:
        limit = min(int(body.get('limit', 20)), 100)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="'limit' must be an integer")
    status = body.get('status', 'pending')
    pending_review = None if status == 'all' else 1
    requirements = await list_by_memory_type('requirement', project, limit,
                                             pending_review=pending_review)
    return {
        'count': len(requirements),
        'requirements': requirements,
        'status': 'success',
    }
