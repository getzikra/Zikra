from zikra.db import fetch_prompt_row, bump_access_count, record_pending_run
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

    # v1.0.6 server-side handshake: if the caller identifies its runner, remember
    # that this runner just fetched this prompt. The next log_run from the same
    # runner will auto-link to it. Silent no-op when runner is absent.
    runner = body.get('runner')
    if runner:
        await record_pending_run(runner, row['id'], project)

    return {
        'id': row['id'],
        'title': row['title'],
        'content_md': row['content_md'],
        'project': row['project'],
        'access_count': row['access_count'] + 1,
    }
