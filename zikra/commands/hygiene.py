"""Orphan / stale memory detection.

A memory is flagged when ALL conditions are true:
  - Not pinned.
  - Idle for more than STALE_DAYS days. The idle clock is
    COALESCE(last_accessed_at, updated_at, created_at) — every search hit or
    explicit fetch refreshes last_accessed_at, so "idle" means genuinely
    unretrieved, not just unedited.
  - Zero incoming wikilinks — nothing currently [[links]] to it.

Verdict:
  - days_idle > 90  → 'archive'
  - days_idle > 30  → 'review'
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
