from zikra.commands import _require_project, _parse_limit
from zikra.db import list_by_memory_type


async def cmd_list_prompts(body: dict) -> dict:
    project = _require_project(body)
    limit = _parse_limit(body, default=50)
    if isinstance(limit, dict):
        return limit
    prompts = await list_by_memory_type('prompt', project, limit)
    return {'count': len(prompts), 'prompts': prompts, 'status': 'success'}
