from zikra.db import list_decisions
from zikra.architecture_utils import canonical_project, required_text


def _chain_order(rows: list) -> list:
    """Order decisions so each supersedes link is adjacent: chain tip first,
    then walk supersedes_id back to the oldest. Orphans/cycles appended last."""
    by_id = {r['id']: r for r in rows}
    pointed_at = {r['supersedes_id'] for r in rows if r.get('supersedes_id')}
    heads = [r for r in rows if r['id'] not in pointed_at]
    heads.sort(key=lambda r: str(r.get('created_at') or ''), reverse=True)

    ordered, seen = [], set()
    for head in heads:
        current = head
        while current is not None and current['id'] not in seen:
            ordered.append(current)
            seen.add(current['id'])
            current = by_id.get(current.get('supersedes_id'))
    for row in rows:  # cycles or rows whose chain link left the module
        if row['id'] not in seen:
            ordered.append(row)
    return ordered


async def cmd_module_history(body: dict) -> dict:
    """Full decision chain for a module, including superseded rows."""
    try:
        project = canonical_project(body.get('project'))
        module = required_text(body.get('module'), 'module', 200)
    except ValueError as exc:
        return {'error': str(exc)}

    rows = await list_decisions(project, module=module, current_only=False)
    history = _chain_order(rows)
    return {'project': project, 'module': module,
            'history': history, 'count': len(history)}
