"""Orphan / stale memory detection.

A memory is flagged when BOTH conditions are true:
  - No updates in STALE_DAYS days (based on updated_at, which the save path
    bumps on every re-save; fall back to created_at if updated_at is NULL).
  - Zero incoming wikilinks — nothing currently [[links]] to it.

Verdict:
  - days_idle > 90  → 'archive'
  - days_idle > 30  → 'review'

The memories table in this repo has no last_accessed_at column, so we use
updated_at as the staleness clock (it is refreshed on every save_memory and
on bump_access_count). That is a looser definition of "idle" than pure
retrieval, but it's the best signal the current schema carries.
"""

from zikra.commands import _require_project
from zikra.db import hygiene_report


async def cmd_hygiene(body: dict) -> dict:
    project = _require_project(body)
    try:
        stale_days = int(body.get('stale_days', 30))
    except (ValueError, TypeError):
        return {'error': "'stale_days' must be an integer"}
    if stale_days < 0:
        stale_days = 0

    rows = await hygiene_report(project=project, stale_days=stale_days)

    results = []
    for r in rows:
        days = int(r.get('days_idle') or 0)
        verdict = 'archive' if days > 90 else 'review'
        results.append({
            'id':             r['id'],
            'title':          r['title'],
            'memory_type':    r.get('memory_type'),
            'project':        r.get('project'),
            'days_idle':      days,
            'access_count':   int(r.get('access_count') or 0),
            'backlink_count': int(r.get('backlink_count') or 0),
            'verdict':        verdict,
        })

    return {
        'project':      project,
        'stale_days':   stale_days,
        'orphan_count': len(results),
        'memories':     results,
    }
