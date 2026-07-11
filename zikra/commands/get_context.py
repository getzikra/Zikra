"""get_context — token-budgeted project digest for session start.

Returns a markdown briefing an agent can inject as context when a session
begins: pinned memories first, then recent decisions, open bugs, and the
highest-scoring remaining memories. Consumed by the SessionStart hook and
the zikra_get_context MCP tool.
"""

from datetime import datetime, timedelta, timezone

from zikra.commands import _require_project
from zikra.db import list_all_memories, log_retrievals
from zikra.scoring import compute_score, _parse_ts

CHARS_PER_TOKEN = 4

SECTION_CAPS = {
    'pinned': 10,
    'decisions': 6,
    'bugs': 4,
    'top': 6,
}
RECENT_DECISION_DAYS = 21


def _clip(text: str, max_chars: int) -> str:
    text = (text or '').strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rsplit(' ', 1)[0] + ' …'


async def cmd_get_context(body: dict) -> dict:
    project = _require_project(body)
    try:
        max_tokens = int(body.get('max_tokens', 2000))
    except (ValueError, TypeError):
        return {'error': 'max_tokens must be an integer'}
    max_tokens = max(200, min(max_tokens, 8000))

    rows = await list_all_memories(project, limit=500)

    now = datetime.now(timezone.utc)
    recent_cutoff = now - timedelta(days=RECENT_DECISION_DAYS)

    def created(m):
        return _parse_ts(m.get('created_at')) or now

    pinned = [m for m in rows if m.get('pinned')]
    decisions = sorted(
        (m for m in rows if m.get('memory_type') == 'decision'
         and not m.get('pinned') and created(m) >= recent_cutoff),
        key=created, reverse=True,
    )
    bugs = sorted(
        (m for m in rows if m.get('memory_type') in ('bug', 'error')
         and not m.get('resolved') and not m.get('pinned')),
        key=created, reverse=True,
    )

    chosen_ids = set()
    sections = []

    def take(items, cap, heading, per_item_chars):
        picked = []
        for m in items:
            if m['id'] in chosen_ids:
                continue
            picked.append(m)
            chosen_ids.add(m['id'])
            if len(picked) >= cap:
                break
        if picked:
            lines = [f'## {heading}']
            for m in picked:
                body_txt = _clip(m.get('content_md') or m.get('snippet') or '', per_item_chars)
                lines.append(f"### {m['title']}\n{body_txt}")
            sections.append('\n'.join(lines))
        return picked

    take(pinned, SECTION_CAPS['pinned'], 'Pinned', 600)
    take(decisions, SECTION_CAPS['decisions'], 'Recent decisions', 450)
    take(bugs, SECTION_CAPS['bugs'], 'Open bugs / blockers', 400)

    remaining = sorted(
        (m for m in rows if m['id'] not in chosen_ids
         and m.get('memory_type') not in ('prompt',)),
        key=lambda m: compute_score(m), reverse=True,
    )
    take(remaining, SECTION_CAPS['top'], 'Most relevant memories', 350)

    header = f'# Zikra context — project: {project}'
    budget_chars = max_tokens * CHARS_PER_TOKEN
    out = [header]
    used = len(header)
    for section in sections:
        if used + len(section) > budget_chars:
            break
        out.append(section)
        used += len(section)

    context_md = '\n\n'.join(out)
    included = list(chosen_ids)
    await log_retrievals(included, 'context')

    return {
        'project': project,
        'context_md': context_md,
        'memories_used': len(included),
        'tokens_estimate': round(len(context_md) / CHARS_PER_TOKEN),
    }
