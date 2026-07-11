"""ingest_session — upload a session transcript tail for server-side
distillation into typed memories.

The Stop hook sends {runner, project, session_id, cwd, transcript_tail}.
When a distiller LLM is configured the tail is queued and distilled in the
background; the hook skips its local `claude -p` diary. When it is not,
the response says so and the hook falls back to the local path.
"""

from zikra import config
from zikra.commands import _require_project
from zikra.db import create_ingest, new_id
from zikra.distill import llm_available, schedule_distill


async def cmd_ingest_session(body: dict) -> dict:
    runner = body.get('runner')
    if not runner:
        return {'error': 'runner is required'}
    tail = body.get('transcript_tail') or ''
    if not tail.strip():
        return {'error': 'transcript_tail is required'}

    if not llm_available():
        return {'status': 'no_distiller',
                'hint': 'set ZIKRA_LLM_API_KEY (or OPENAI_API_KEY) on the server to enable distillation'}

    if len(tail.encode('utf-8', errors='replace')) > config.DISTILL_MAX_TAIL_BYTES:
        tail = tail[-config.DISTILL_MAX_TAIL_BYTES:]

    ingest_id = new_id()
    await create_ingest({
        'runner': runner,
        'project': _require_project(body),
        'session_id': body.get('session_id'),
        'cwd': body.get('cwd'),
        'transcript_tail': tail,
    }, ingest_id)
    schedule_distill(ingest_id)
    return {'id': ingest_id, 'status': 'queued'}
