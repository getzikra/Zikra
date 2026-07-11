"""get_context briefing (v1.1.0).

Pinned memories always lead, recent decisions and open bugs follow, the
result respects max_tokens, and included memories are logged as
source='context' retrievals.
"""

import asyncio
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import zikra.commands as commands
import zikra.db as db
from zikra.commands.get_context import cmd_get_context
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


async def _run(db_path):
    os.environ['DB_BACKEND'] = 'sqlite'
    os.environ['ZIKRA_DB_PATH'] = str(db_path)

    vector = [1.0] + [0.0] * 1535

    async def fake_embed(_text):
        return vector

    old_embed = commands.embed
    old_dedup = commands.config.SAVE_DEDUP_ENABLED
    old_reclass = commands.config.PROJECT_RECLASSIFY_ENABLED
    commands.embed = fake_embed
    commands.config.SAVE_DEDUP_ENABLED = False
    commands.config.PROJECT_RECLASSIFY_ENABLED = False
    aio = await _reset_sqlite(db_path)
    try:
        await cmd_save_memory({'title': 'always remember the deploy runbook',
                               'content_md': 'backup db first, then rebuild',
                               'project': 'proj-a', 'memory_type': 'reference', 'pinned': 1})
        await cmd_save_memory({'title': 'we chose postgres over sqlite',
                               'content_md': 'team scale needs pgvector',
                               'project': 'proj-a', 'memory_type': 'decision'})
        await cmd_save_memory({'title': 'login 500 on prod',
                               'content_md': 'apache proxy misroutes /api',
                               'project': 'proj-a', 'memory_type': 'bug'})
        await cmd_save_memory({'title': 'unrelated other project note',
                               'content_md': 'should not appear',
                               'project': 'proj-b', 'memory_type': 'note'})

        res = await cmd_get_context({'project': 'proj-a', 'max_tokens': 2000})
        ctx = res['context_md']
        assert 'deploy runbook' in ctx, ctx
        assert 'postgres over sqlite' in ctx, ctx
        assert 'login 500' in ctx, ctx
        assert 'unrelated other project' not in ctx, ctx
        assert ctx.index('Pinned') < ctx.index('Recent decisions') < ctx.index('Open bugs'), ctx
        assert res['memories_used'] == 3, res
        assert res['tokens_estimate'] <= 2000

        # retrievals logged as source=context
        async with aio.execute(
            "SELECT COUNT(*) AS n FROM retrievals WHERE source='context'"
        ) as cur:
            assert (await cur.fetchone())['n'] == 3

        # tight budget → header always present, sections trimmed
        res2 = await cmd_get_context({'project': 'proj-a', 'max_tokens': 200})
        assert res2['tokens_estimate'] <= 220, res2
    finally:
        commands.embed = old_embed
        commands.config.SAVE_DEDUP_ENABLED = old_dedup
        commands.config.PROJECT_RECLASSIFY_ENABLED = old_reclass
        await aio.close()
        db._aio_db = None
        if db._db is not None:
            db._db.close()
            db._db = None


def test_get_context_sqlite():
    with tempfile.TemporaryDirectory() as tmpdir:
        asyncio.run(_run(Path(tmpdir) / 'get_context.db'))


if __name__ == '__main__':
    test_get_context_sqlite()
    print('PASS: test_get_context_sqlite')
