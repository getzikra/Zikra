from zikra.db import store_memory
from zikra.embed import embed

_EMBED_WARNING = 'semantic embedding unavailable; keyword search only for this entry'


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
    embedding = raw if raw is not None else [0.0] * 1536
    memory_id = await store_memory(data, embedding)
    return memory_id, raw is None
