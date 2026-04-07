from zikra.commands import _require_project, _parse_limit
from zikra.db import list_by_memory_type

VALID_STATUSES = {'pending', 'resolved'}


async def cmd_list_requirements(body: dict) -> dict:
    project = _require_project(body)
    limit = _parse_limit(body, default=20)
    if isinstance(limit, dict):
        return limit
    status = body.get('status') or None
    if status and status not in VALID_STATUSES:
        return {
            'error': f"Invalid status '{status}'",
            'valid_values': sorted(VALID_STATUSES),
        }
    requirements = await list_by_memory_type('requirement', project, limit, status=status)
    return {'count': len(requirements), 'requirements': requirements, 'status': 'success'}
