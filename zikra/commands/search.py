from zikra.db import find_memories
from zikra.embed import embed
from zikra.commands import _require_project, _parse_limit
from zikra.config import SNIPPET_LENGTHS

CHARS_PER_TOKEN = 4

VALID_MEMORY_TYPES = {
    'conversation', 'decision', 'requirement', 'error', 'prompt', 'note',
}


def apply_token_budget(results: list, max_tokens: int) -> tuple:
    budget_chars = max_tokens * CHARS_PER_TOKEN
    total_chars = 0
    output = []
    for i, r in enumerate(results):
        max_len = SNIPPET_LENGTHS[i] if i < len(SNIPPET_LENGTHS) else 150
        snippet = (r.get('snippet') or '')[:max_len]
        entry_chars = len(r.get('title', '')) + len(snippet)
        if total_chars + entry_chars > budget_chars and output:
            break
        total_chars += entry_chars
        output.append({**r, 'snippet': snippet})
    return output, round(total_chars / CHARS_PER_TOKEN)


async def cmd_search(body: dict) -> dict:
    query = body.get('query') or body.get('q') or body.get('text', '')
    project = _require_project(body)
    limit = _parse_limit(body, default=10, maximum=100)
    if isinstance(limit, dict):
        return {**limit, 'results': []}
    limit = max(1, limit)
    try:
        max_tokens = int(body.get('max_tokens', 2000))
    except (ValueError, TypeError):
        return {'error': 'max_tokens must be an integer', 'results': []}

    memory_type = body.get('memory_type') or None
    if memory_type and memory_type not in VALID_MEMORY_TYPES:
        return {
            'error': f"Invalid memory_type '{memory_type}'",
            'valid_types': sorted(VALID_MEMORY_TYPES),
            'results': [],
        }

    if not query:
        return {'error': 'query is required', 'results': []}

    query_embedding = await embed(query)
    embedding_warning = None
    if query_embedding is None:
        query_embedding = [0.0] * 1536
        embedding_warning = 'semantic search unavailable, results are keyword-only'

    results_list, fts_degraded, fts_reason = await find_memories(
        query, query_embedding, project, limit, memory_type=memory_type
    )
    results, tokens_used = apply_token_budget(results_list, max_tokens)

    response = {'results': results, 'count': len(results), 'tokens_used': tokens_used}
    if embedding_warning:
        response['degraded'] = True
        response['warning'] = embedding_warning
    if fts_degraded:
        response['degraded'] = True
        response['degraded_reason'] = fts_reason
    return response
