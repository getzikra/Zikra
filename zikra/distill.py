"""Server-side transcript distillation.

Turns a raw session transcript tail (uploaded by the Stop hook via
ingest_session) into typed memories: one 'conversation' diary plus zero or
more decision / bug / reference memories. Uses any OpenAI-compatible chat
completions endpoint — see the ZIKRA_LLM_* settings in config.py.

Nothing here runs unless llm_available() is true; the webhook tells the
hook so, and the hook falls back to its local `claude -p` diary path.
"""

import asyncio
import json
import logging
import os
import re

import httpx

from zikra import config
from zikra.db import fetch_ingest, finish_ingest, record_run, new_id

logger = logging.getLogger(__name__)

_semaphore: asyncio.Semaphore = None

DISTILL_TYPES = {'decision', 'bug', 'reference'}

_PROMPT = """You are a memory distiller for a persistent AI-agent memory system.
Below is the tail of a coding-session transcript (JSONL from an AI coding CLI).

Extract durable knowledge from it. Respond with ONLY a JSON object, no prose,
no code fences:

{
  "diary": "<complete first-person diary of the session: what was built/fixed/deployed with file names and specifics, key decisions and WHY, problems and resolutions, current state and what's left. 300-500 words, markdown allowed>",
  "memories": [
    {
      "memory_type": "decision" | "bug" | "reference",
      "title": "<short specific title, max 90 chars>",
      "content_md": "<the durable fact. For decisions: what was decided and why. For bugs: symptom, root cause, fix. For references: what/where. 30-150 words>"
    }
  ]
}

Rules:
- Only include memories that stay true AFTER the session ends: decisions with
  rationale, root-caused bugs, discovered constraints or resources. No
  play-by-play, no "we are currently doing X".
- 0-5 memories. An uneventful session yields an empty list.
- Titles must be self-contained (a reader sees the title in a list with no
  other context)."""


def _llm_conf() -> dict:
    """Re-read env at call time — .env may load after config import."""
    return {
        'base_url': (os.getenv('ZIKRA_LLM_BASE_URL') or config.LLM_BASE_URL).rstrip('/'),
        'model': os.getenv('ZIKRA_LLM_MODEL') or config.LLM_MODEL,
        'api_key': os.getenv('ZIKRA_LLM_API_KEY') or os.getenv('OPENAI_API_KEY') or config.LLM_API_KEY,
        'timeout': config.LLM_TIMEOUT_S,
    }


def llm_available() -> bool:
    return config.DISTILL_ENABLED and bool(_llm_conf()['api_key'])


async def _chat(prompt: str, user_content: str) -> str:
    c = _llm_conf()
    async with httpx.AsyncClient(timeout=c['timeout']) as client:
        resp = await client.post(
            f"{c['base_url']}/chat/completions",
            headers={'Authorization': f"Bearer {c['api_key']}"},
            json={
                'model': c['model'],
                'messages': [
                    {'role': 'system', 'content': prompt},
                    {'role': 'user', 'content': user_content},
                ],
                'temperature': 0.2,
            },
        )
        resp.raise_for_status()
        return resp.json()['choices'][0]['message']['content']


def _parse_json_reply(text: str) -> dict:
    """Parse the LLM reply, tolerating code fences and leading prose."""
    text = text.strip()
    fence = re.search(r'```(?:json)?\s*(\{.*\})\s*```', text, re.DOTALL)
    if fence:
        text = fence.group(1)
    elif not text.startswith('{'):
        brace = text.find('{')
        if brace >= 0:
            text = text[brace:]
    return json.loads(text)


async def distill_ingest(ingest_id: str) -> None:
    """Distill one queued ingest into memories. Never raises."""
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(config.DISTILL_CONCURRENCY)

    async with _semaphore:
        try:
            row = await fetch_ingest(ingest_id)
            if not row or row.get('status') != 'pending':
                return
            if not llm_available():
                await finish_ingest(ingest_id, 'skipped', error='no LLM configured')
                return

            reply = await _chat(_PROMPT, row['transcript_tail'])
            parsed = _parse_json_reply(reply)
            diary = (parsed.get('diary') or '').strip()
            memories = parsed.get('memories') or []

            from zikra.commands import _embed_and_store

            created = 0
            runner = row.get('runner') or 'unknown'
            project = row.get('project') or 'global'
            sid8 = (row.get('session_id') or '')[:8]

            if diary:
                date = (row.get('created_at') or '')[:10]
                title = f"diary:{date}:{sid8}:{runner}" if sid8 else f"diary:{date}:{runner}"
                await _embed_and_store({
                    'title': title,
                    'content_md': diary,
                    'project': project,
                    'memory_type': 'conversation',
                    'created_by': runner,
                }, title)
                created += 1
                # Enrich the session's run row with the distilled narrative
                if row.get('session_id'):
                    await record_run({
                        'project': project,
                        'runner': runner,
                        'session_id': row['session_id'],
                        'output_summary': diary,
                    }, new_id())

            for m in memories[:5]:
                mtype = m.get('memory_type')
                title = (m.get('title') or '').strip()[:120]
                content = (m.get('content_md') or '').strip()
                if mtype not in DISTILL_TYPES or not title or not content:
                    continue
                await _embed_and_store({
                    'title': title,
                    'content_md': content,
                    'project': project,
                    'memory_type': mtype,
                    'created_by': runner,
                    'pending_review': 1,
                }, title)
                created += 1

            await finish_ingest(ingest_id, 'distilled', memories_created=created)
            logger.info(f'distilled ingest {ingest_id}: {created} memories ({project}/{runner})')
        except Exception as e:
            logger.exception(f'distillation failed for ingest {ingest_id}')
            try:
                await finish_ingest(ingest_id, 'failed', error=str(e)[:500])
            except Exception:
                pass


def schedule_distill(ingest_id: str) -> None:
    """Fire-and-forget distillation from a request handler."""
    asyncio.get_event_loop().create_task(distill_ingest(ingest_id))


async def drain_pending() -> None:
    """Process ingests left 'pending' by a crash/restart. Called at startup."""
    from zikra.db import list_pending_ingests
    try:
        pending = await list_pending_ingests(limit=50)
    except Exception:
        logger.exception('could not list pending ingests')
        return
    for ingest_id in pending:
        await distill_ingest(ingest_id)
