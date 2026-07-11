import logging

from zikra import config
from zikra.db import record_error, count_recent_errors, new_id

logger = logging.getLogger(__name__)


async def cmd_log_error(body: dict) -> dict:
    message = body.get('message') or body.get('error', '')
    if not message or not message.strip():
        return {
            'error': "message is required (use field name 'message' or 'error')",
            'hint': "field name 'title' is not stored — use 'message' instead",
        }
    error_id = new_id()
    await record_error(body, error_id)
    result = {'id': error_id, 'status': 'logged'}

    # Recurring identical errors graduate into a searchable bug memory —
    # one-off noise stays in error_log only.
    try:
        project = body.get('project', 'global')
        error_type = body.get('error_type')
        n = await count_recent_errors(project, error_type, message,
                                      days=config.ERROR_PROMOTE_WINDOW_DAYS)
        if n >= config.ERROR_PROMOTE_THRESHOLD:
            from zikra.commands import _embed_and_store
            title = f'recurring error: {message.strip()[:100]}'
            content = (
                f'Seen {n}x in the last {config.ERROR_PROMOTE_WINDOW_DAYS} days '
                f'(project {project}, type {error_type or "unspecified"}).\n\n'
                f'**Message:** {message.strip()[:500]}\n\n'
                f'**Last context:**\n{(body.get("context_md") or body.get("stack_trace") or "")[:1500]}'
            )
            await _embed_and_store({
                'title': title,
                'content_md': content,
                'project': project,
                'memory_type': 'bug',
                'created_by': body.get('runner'),
                'pending_review': 1,
            }, title)
            result['promoted'] = True
            result['occurrences'] = n
    except Exception:
        logger.exception('error promotion failed')

    return result
