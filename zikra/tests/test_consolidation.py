"""Weekly consolidation (v1.1.0).

Old diaries in the same ISO week get distilled (fake LLM) into
pending_review decision/reference memories and the sources are archived
(searchable=0). Pinned and recent diaries are untouched; dry_run archives
nothing.
"""

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import zikra.commands as commands
import zikra.consolidate as consolidate
import zikra.db as db
from zikra.commands.save_memory import cmd_save_memory


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


FAKE_REPLY = json.dumps({'memories': [
    {'memory_type': 'decision', 'title': 'switched CI to pull-based deploys',
     'content_md': 'Decided pull-based via tunnel because inbound ports are closed.'},
]})


async def _run(db_path):
    os.environ['DB_BACKEND'] = 'sqlite'
    os.environ['ZIKRA_DB_PATH'] = str(db_path)

    vector = [1.0] + [0.0] * 1535

    async def fake_embed(_text):
        return vector

    async def fake_chat(_prompt, _content):
        return FAKE_REPLY

    old_embed = commands.embed
    old_chat = consolidate._chat
    old_avail = consolidate.llm_available
    consolidate.llm_available = lambda: True
    old_dedup = commands.config.SAVE_DEDUP_ENABLED
    old_reclass = commands.config.PROJECT_RECLASSIFY_ENABLED
    commands.embed = fake_embed
    consolidate._chat = fake_chat
    commands.config.SAVE_DEDUP_ENABLED = False
    commands.config.PROJECT_RECLASSIFY_ENABLED = False
    aio = await _reset_sqlite(db_path)
    try:
        for i in range(3):
            await cmd_save_memory({'title': f'diary:old-{i}', 'content_md': f'old diary {i}',
                                   'project': 'proj-a', 'memory_type': 'conversation'})
        await cmd_save_memory({'title': 'diary:pinned', 'content_md': 'pinned diary',
                               'project': 'proj-a', 'memory_type': 'conversation', 'pinned': 1})
        await cmd_save_memory({'title': 'diary:recent', 'content_md': 'recent diary',
                               'project': 'proj-a', 'memory_type': 'conversation'})
        # Backdate the three old diaries into one ISO week, 30 days ago
        await aio.execute(
            "UPDATE memories SET created_at = datetime('now', '-30 days') WHERE title LIKE 'diary:old-%'")
        await aio.commit()

        # dry_run: reports the cluster, archives nothing
        dry = await consolidate.run_consolidation(project='proj-a', dry_run=True)
        assert dry['status'] == 'ok' and dry['dry_run'] is True, dry
        assert dry['projects'][0]['weeks'][0]['sources'] == 3, dry
        async with aio.execute("SELECT COUNT(*) AS n FROM memories WHERE searchable=0") as cur:
            assert (await cur.fetchone())['n'] == 0

        # real run
        res = await consolidate.run_consolidation(project='proj-a')
        summary = res['projects'][0]
        assert summary['memories_created'] == 1, summary
        assert summary['diaries_archived'] == 3, summary

        async with aio.execute(
            "SELECT title, memory_type, pending_review, searchable FROM memories") as cur:
            rows = {r['title']: dict(r) for r in await cur.fetchall()}

        assert rows['switched CI to pull-based deploys']['pending_review'] == 1
        assert rows['switched CI to pull-based deploys']['memory_type'] == 'decision'
        for i in range(3):
            assert rows[f'diary:old-{i}']['searchable'] == 0, rows[f'diary:old-{i}']
        assert rows['diary:pinned']['searchable'] == 1
        assert rows['diary:recent']['searchable'] == 1
    finally:
        commands.embed = old_embed
        consolidate._chat = old_chat
        consolidate.llm_available = old_avail
        commands.config.SAVE_DEDUP_ENABLED = old_dedup
        commands.config.PROJECT_RECLASSIFY_ENABLED = old_reclass
        await aio.close()
        db._aio_db = None
        if db._db is not None:
            db._db.close()
            db._db = None


def test_consolidation_sqlite():
    with tempfile.TemporaryDirectory() as tmpdir:
        asyncio.run(_run(Path(tmpdir) / 'consolidation.db'))


if __name__ == '__main__':
    test_consolidation_sqlite()
    print('PASS: test_consolidation_sqlite')
