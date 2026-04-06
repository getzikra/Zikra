from fastapi import HTTPException

from zikra.db import list_by_memory_type


async def cmd_list_prompts(body: dict) -> dict:
    project = body.get('project', 'global')
    try:
        limit = min(int(body.get('limit', 50)), 100)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="'limit' must be an integer")
    prompts = await list_by_memory_type('prompt', project, limit)
    return {
        'count': len(prompts),
        'prompts': prompts,
        'status': 'success',
    }
