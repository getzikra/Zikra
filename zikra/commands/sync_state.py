from zikra.db import get_sync_state, set_sync_state
from zikra.architecture_utils import absolute_repo_path, canonical_project, required_text


async def cmd_get_sync_state(body: dict) -> dict:
    try:
        project = canonical_project(body.get('project'))
        repo_path = absolute_repo_path(body.get('repo_path'))
    except ValueError as exc:
        return {'error': str(exc)}

    row = await get_sync_state(project, repo_path)
    if not row:
        return {'project': project, 'repo_path': repo_path,
                'last_synced_commit': None, 'synced_at': None, 'status': 'not_found'}
    return {**row, 'status': 'ok'}


async def cmd_set_sync_state(body: dict) -> dict:
    try:
        project = canonical_project(body.get('project'))
        repo_path = absolute_repo_path(body.get('repo_path'))
        commit = required_text(
            body.get('last_synced_commit') or body.get('commit'),
            'last_synced_commit', 200,
        )
    except ValueError as exc:
        return {'error': str(exc)}

    row = await set_sync_state(project, repo_path, commit)
    return {**row, 'status': 'saved'}
