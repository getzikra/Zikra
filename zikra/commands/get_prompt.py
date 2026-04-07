from zikra.db import fetch_prompt_row, bump_access_count
from zikra.commands import _require_project


async def cmd_get_prompt(body: dict) -> dict:
    prompt_name = body.get('prompt_name') or body.get('name') or body.get('title', '')
    project = _require_project(body)
    if not prompt_name:
        return {'error': 'prompt_name is required'}

    row = await fetch_prompt_row(prompt_name, project=project)
    if not row:
        return {'error': f'Prompt not found: {prompt_name}'}

    await bump_access_count(row['id'])

    return {
        'id': row['id'],
        'title': row['title'],
        'content_md': row['content_md'],
        'project': row['project'],
        'access_count': row['access_count'] + 1,
    }
