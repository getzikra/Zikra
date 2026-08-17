from zikra.db import list_decisions
from zikra.architecture_utils import canonical_project, environment as validate_environment


async def cmd_get_architecture(body: dict) -> dict:
    """All status='current' decisions for a project, newest first, full content.
    With module: flat list for that module. Without: grouped by module."""
    try:
        project = canonical_project(body.get('project'))
        environment = validate_environment(body.get('environment'))
    except ValueError as exc:
        return {'error': str(exc)}
    module = body.get('module')
    if module is not None and (not isinstance(module, str) or not module.strip()):
        return {'error': 'module must be a non-empty string'}
    module = module.strip() if module else None

    rows = await list_decisions(project, module=module, environment=environment,
                                current_only=True)

    if module:
        return {'project': project, 'module': module,
                'decisions': rows, 'count': len(rows)}

    grouped: dict = {}
    for row in rows:
        grouped.setdefault(row.get('module') or '_global', []).append(row)
    return {'project': project, 'modules': grouped, 'count': len(rows)}
