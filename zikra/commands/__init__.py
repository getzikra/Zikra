import logging

from zikra import config
from zikra.db import find_recent_similar, nearest_projects, store_memory, update_memory_content
from zikra.embed import embed

_EMBED_WARNING = 'semantic embedding unavailable; keyword search only for this entry'
logger = logging.getLogger(__name__)


def _require_project(body: dict, default: str = 'global') -> str:
    """Return the project from the request body, falling back to default."""
    return body.get('project') or default


def _parse_limit(body: dict, default: int, maximum: int = 100) -> 'int | dict':
    """Parse and clamp 'limit'. Returns error dict on invalid input (no exceptions)."""
    try:
        return min(int(body.get('limit', default)), maximum)
    except (ValueError, TypeError):
        return {'error': "'limit' must be an integer"}


async def _embed_and_store(data: dict, title: str) -> tuple:
    """Embed title+content and store to db. Returns (memory_id, embedding_degraded)."""
    content = data.get('content_md') or data.get('content', '')
    raw = await embed(f'{title} {content}')
    degraded = raw is None
    embedding = raw if raw is not None else [0.0] * 1536
    memory_type = data.get('memory_type') or 'conversation'

    if not degraded and config.PROJECT_RECLASSIFY_ENABLED and memory_type in config.PROJECT_RECLASSIFY_TYPES:
        try:
            voted = await _vote_project(embedding, data.get('project'))
            if voted:
                data = {**data, 'project': voted}
        except Exception:
            logger.exception('write-time project reclassify failed')

    if not degraded and config.SAVE_DEDUP_ENABLED and memory_type in config.SAVE_DEDUP_TYPES:
        try:
            match = await find_recent_similar(
                data.get('created_by'),
                data.get('project') or 'global',
                list(config.SAVE_DEDUP_TYPES),
                config.SAVE_DEDUP_WINDOW_MIN,
                embedding,
            )
            if match and match['sim'] >= config.SAVE_DEDUP_SIM_THRESHOLD:
                await update_memory_content(match['id'], content, embedding)
                return match['id'], degraded
        except Exception:
            logger.exception('write-time save dedup failed')

    memory_id = await store_memory(data, embedding)
    return memory_id, degraded


async def _vote_project(embedding, current):
    rows = await nearest_projects(embedding, config.PROJECT_RECLASSIFY_K)
    rows = [r for r in rows if r['sim'] >= config.PROJECT_RECLASSIFY_MIN_SIM]
    if len(rows) < config.PROJECT_RECLASSIFY_MIN_VOTES:
        return None
    from collections import Counter
    proj, n = Counter(r['project'] for r in rows).most_common(1)[0]
    if proj and proj != current and (n / len(rows)) >= config.PROJECT_RECLASSIFY_MIN_AGREE:
        return proj
    return None
