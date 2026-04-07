from zikra.commands import _require_project, _parse_limit
from zikra.db import list_by_memory_type


async def cmd_list_requirements(body: dict) -> dict:
    project = _require_project(body)
    limit = _parse_limit(body, default=20)
    if isinstance(limit, dict):
        return limit
    status = body.get('status', 'pending')
    pending_review = None if status == 'all' else 1
    requirements = await list_by_memory_type('requirement', project, limit,
                                             pending_review=pending_review)
    return {'count': len(requirements), 'requirements': requirements, 'status': 'success'}
