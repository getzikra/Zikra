"""Server-side distiller (v1.1.0).

With a faked LLM, ingest_session must queue a transcript tail and
distill_ingest must turn it into a conversation diary + typed memories
(pending_review=1) and enrich the session's run row. Without an LLM,
ingest_session must answer no_distiller so the hook can fall back.
"""

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import zikra.commands as commands
import zikra.db as db
import zikra.distill as distill
from zikra.commands.ingest_session import cmd_ingest_session


async def _reset_sqlite(path):
    if db._aio_db is not None:
        await db._aio_db.close()
    if db._db is not None:
        db._db.close()
    db._aio_db = None
    db._db = None
    db._is_pg = False

    db.init_db()
    aio = await db.open_aio_db(str(path))
    db.set_aio_db(aio)
    return aio


FAKE_REPLY = json.dumps({
    'diary': 'Today I wired the frobnicator to the flux capacitor and fixed the timing bug.',
    'memories': [
        {'memory_type': 'decision', 'title': 'Use flux capacitor for timing',
         'content_md': 'Chose the flux capacitor because it is deterministic.'},
        {'memory_type': 'bug', 'title': 'Timing bug in frobnicator',
         'content_md': 'Symptom: drift. Root cause: off-by-one. Fix: clamp.'},
        {'memory_type': 'nonsense', 'title': 'should be dropped', 'content_md': 'x'},
    ],
})


async def _run(db_path):
    os.environ['DB_BACKEND'] = 'sqlite'
    os.environ['ZIKRA_DB_PATH'] = str(db_path)
    aio = await _reset_sqlite(db_path)

    vector = [1.0] + [0.0] * 1535

    async def fake_embed(_text):
        return vector

    async def fake_chat(_prompt, _content):
        return FAKE_REPLY

    old_embed = commands.embed
    old_chat = distill._chat
    old_avail = distill.llm_available
    old_dedup = commands.config.SAVE_DEDUP_ENABLED
    old_reclass = commands.config.PROJECT_RECLASSIFY_ENABLED
    commands.embed = fake_embed
    distill._chat = fake_chat
    commands.config.SAVE_DEDUP_ENABLED = False
    commands.config.PROJECT_RECLASSIFY_ENABLED = False
    try:
        # no LLM → no_distiller, nothing stored
        distill.llm_available = lambda: False
        # cmd module captured the function by reference? no — it imports the name.
        import zikra.commands.ingest_session as ing_mod
        old_mod_avail = ing_mod.llm_available
        ing_mod.llm_available = lambda: False
        r = await cmd_ingest_session({'runner': 'host1', 'transcript_tail': 'x', 'project': 'proj-a'})
        assert r['status'] == 'no_distiller', r

        # LLM available → queued + distilled
        ing_mod.llm_available = lambda: True
        distill.llm_available = lambda: True
        r = await cmd_ingest_session({
            'runner': 'host1', 'project': 'proj-a', 'session_id': 'sess-abc',
            'transcript_tail': '{"fake": "transcript"}\n' * 20,
        })
        assert r['status'] == 'queued', r
        await distill.distill_ingest(r['id'])

        row = await db.fetch_ingest(r['id'])
        assert row['status'] == 'distilled', row
        assert row['memories_created'] == 3, row
        assert row['transcript_tail'] == ''  # tail dropped after distillation

        async with aio.execute(
            "SELECT title, memory_type, pending_review FROM memories ORDER BY memory_type"
        ) as cur:
            mems = [dict(m) for m in await cur.fetchall()]
        types = sorted(m['memory_type'] for m in mems)
        assert types == ['bug', 'conversation', 'decision'], mems
        for m in mems:
            if m['memory_type'] != 'conversation':
                assert m['pending_review'] == 1, m

        async with aio.execute(
            "SELECT output_summary FROM prompt_runs WHERE session_id='sess-abc'"
        ) as cur:
            run = await cur.fetchone()
        assert run and 'flux capacitor' in run['output_summary'], run

        # failed LLM → status failed, error captured
        async def broken_chat(_p, _c):
            raise RuntimeError('llm exploded')
        distill._chat = broken_chat
        r2 = await cmd_ingest_session({
            'runner': 'host1', 'project': 'proj-a', 'transcript_tail': 'y' * 100,
        })
        await distill.distill_ingest(r2['id'])
        row2 = await db.fetch_ingest(r2['id'])
        assert row2['status'] == 'failed' and 'llm exploded' in row2['error'], row2
        assert row2['transcript_tail'] == '', row2

        ing_mod.llm_available = old_mod_avail
    finally:
        commands.embed = old_embed
        distill._chat = old_chat
        distill.llm_available = old_avail
        commands.config.SAVE_DEDUP_ENABLED = old_dedup
        commands.config.PROJECT_RECLASSIFY_ENABLED = old_reclass
        await aio.close()
        db._aio_db = None
        if db._db is not None:
            db._db.close()
            db._db = None


def test_distiller_sqlite():
    with tempfile.TemporaryDirectory() as tmpdir:
        asyncio.run(_run(Path(tmpdir) / 'distiller.db'))


if __name__ == '__main__':
    test_distiller_sqlite()
    print('PASS: test_distiller_sqlite')
