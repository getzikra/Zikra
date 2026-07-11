"""Scheduled consolidation — the automatic version of the memory-hygiene run.

Old conversation/diary memories are grouped per project and ISO week, each
group is distilled by the LLM into a handful of durable decision/reference/
bug memories (pending_review=1 so a human approves them in the dashboard),
and the source diaries are archived (searchable=0 — reversible, nothing is
deleted).

Runs weekly in the background when a distiller LLM is configured; can be
triggered manually via the run_consolidation command.
"""

import asyncio
import logging
import os
import time
from datetime import datetime, timezone

from zikra import config
from zikra.distill import _chat, _parse_json_reply, llm_available
from zikra.scoring import _parse_ts

logger = logging.getLogger(__name__)

_PROMPT = """You are consolidating one week of auto-captured session diaries from an
AI-agent memory system into durable knowledge.

Below are several diary entries (project: {project}, week: {week}).
Respond with ONLY a JSON object, no prose, no code fences:

{{
  "memories": [
    {{
      "memory_type": "decision" | "reference" | "bug",
      "title": "<short specific self-contained title, max 90 chars>",
      "content_md": "<the durable fact: decisions with WHY, root-caused bugs with fixes, discovered constraints/resources. 30-200 words>"
    }}
  ]
}}

Rules:
- Only facts that remain true after the week ended. Skip play-by-play,
  superseded states, and anything a later entry contradicts.
- Merge duplicates across entries into one memory.
- 0-8 memories. Quality over quantity."""


def _week_key(created_at) -> str:
    ts = _parse_ts(created_at) or datetime.now(timezone.utc)
    iso = ts.isocalendar()
    return f'{iso[0]}-W{iso[1]:02d}'


async def consolidate_project(project: str, dry_run: bool = False) -> dict:
    """Consolidate one project's old diaries. Returns a summary dict."""
    from zikra.commands import _embed_and_store
    from zikra.db import list_consolidation_candidates, archive_memories

    rows = await list_consolidation_candidates(
        project, config.CONSOLIDATE_MIN_AGE_DAYS, config.CONSOLIDATE_BATCH)

    clusters: dict = {}
    for r in rows:
        clusters.setdefault(_week_key(r.get('created_at')), []).append(r)

    created_total = 0
    archived_total = 0
    weeks = []
    for week, members in sorted(clusters.items()):
        if len(members) < 2:
            continue  # a lone diary isn't worth an LLM call; it ages out via hygiene
        corpus = '\n\n---\n\n'.join(
            f"## {m['title']} ({m.get('created_at', '')})\n{m.get('content_md') or ''}"
            for m in members
        )[:config.CONSOLIDATE_MAX_CLUSTER_CHARS]

        if dry_run:
            weeks.append({'week': week, 'sources': len(members), 'created': 0, 'dry_run': True})
            continue

        try:
            reply = await _chat(_PROMPT.format(project=project, week=week), corpus)
            memories = (_parse_json_reply(reply).get('memories') or [])[:8]
        except Exception as e:
            logger.exception(f'consolidation LLM failed for {project}/{week}')
            weeks.append({'week': week, 'sources': len(members), 'error': str(e)[:200]})
            continue

        created = 0
        for m in memories:
            mtype = m.get('memory_type')
            title = (m.get('title') or '').strip()[:120]
            content = (m.get('content_md') or '').strip()
            if mtype not in ('decision', 'reference', 'bug') or not title or not content:
                continue
            await _embed_and_store({
                'title': title,
                'content_md': content + f'\n\n_(consolidated from {len(members)} session diaries, {week})_',
                'project': project,
                'memory_type': mtype,
                'created_by': 'zikra-consolidator',
                'pending_review': 1,
            }, title)
            created += 1

        await archive_memories([m['id'] for m in members],
                               f'consolidated ({week}, {created} memories)')
        created_total += created
        archived_total += len(members)
        weeks.append({'week': week, 'sources': len(members), 'created': created})

    return {
        'project': project,
        'candidates': len(rows),
        'weeks': weeks,
        'memories_created': created_total,
        'diaries_archived': archived_total,
    }


async def run_consolidation(project: str = None, dry_run: bool = False) -> dict:
    from zikra.db import list_projects
    if not llm_available():
        return {'status': 'skipped', 'reason': 'no LLM configured'}
    projects = [project] if project else await list_projects()
    results = []
    for p in projects:
        try:
            results.append(await consolidate_project(p, dry_run=dry_run))
        except Exception as e:
            logger.exception(f'consolidation failed for project {p}')
            results.append({'project': p, 'error': str(e)[:200]})
    return {'status': 'ok', 'dry_run': dry_run, 'projects': results}


# ── Background scheduler ──────────────────────────────────────────────────────

def _marker_path() -> str:
    return os.path.expanduser(
        os.getenv('ZIKRA_CONSOLIDATE_MARKER', '~/.zikra/last_consolidation'))


def _last_run() -> float:
    try:
        return os.path.getmtime(_marker_path())
    except OSError:
        return 0.0


def _touch_marker() -> None:
    path = _marker_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            f.write(str(time.time()))
    except OSError:
        logger.warning(f'could not write consolidation marker {path}')


async def scheduler_loop() -> None:
    """Hourly check; consolidates when the interval has elapsed."""
    if not config.CONSOLIDATE_ENABLED:
        return
    interval_s = config.CONSOLIDATE_INTERVAL_HOURS * 3600
    if _last_run() == 0.0:
        _touch_marker()  # first boot: start the clock, don't consolidate a fresh install
    while True:
        await asyncio.sleep(3600)
        try:
            if time.time() - _last_run() < interval_s or not llm_available():
                continue
            _touch_marker()
            summary = await run_consolidation()
            logger.info(f'scheduled consolidation: {summary}')
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception('scheduled consolidation crashed; will retry next interval')
