from zikra.commands import _EMBED_WARNING
from zikra.architecture_utils import (
    canonical_project,
    environment as validate_environment,
    optional_text,
    required_text,
)
from zikra.db import save_decision
from zikra.embed import embed


async def cmd_save_decision(body: dict) -> dict:
    try:
        title = required_text(body.get('title'), 'title', 300)
        module = required_text(body.get('module'), 'module', 200)
        project = canonical_project(body.get('project'))
        environment = validate_environment(body.get('environment'))
        evidence = optional_text(body.get('evidence'), 'evidence', 2000)
        supersedes_id = optional_text(body.get('supersedes_id'), 'supersedes_id', 100)
    except ValueError as exc:
        return {'error': str(exc)}

    content = body.get('content_md') or body.get('content', '')
    if not isinstance(content, str):
        return {'error': 'content_md must be a string'}
    if len(content) > 500_000:
        return {'error': 'content_md must be 500000 characters or fewer'}
    raw = await embed(f'{title} {content}')
    degraded = raw is None
    embedding = raw if raw is not None else [0.0] * 1536

    data = {
        **body,
        'title': title,
        'module': module,
        'project': project,
        'environment': environment,
        'evidence': evidence,
        'supersedes_id': supersedes_id,
        'memory_type': 'decision',
        'decision_kind': 'architecture',
    }
    try:
        decision_id = await save_decision(data, embedding)
    except ValueError as exc:
        return {'error': str(exc)}

    result = {
        'id': decision_id,
        'title': title,
        'module': module,
        'project': project,
        'status': 'saved',
    }
    if supersedes_id:
        result['superseded'] = supersedes_id
    if degraded:
        result['warning'] = _EMBED_WARNING
    return result
