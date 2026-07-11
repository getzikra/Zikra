"""Recurring-error promotion (v1.1.0).

The same error logged ERROR_PROMOTE_THRESHOLD times within the window must
create a searchable 'bug' memory (pending_review=1); one-offs must not.
"""

import asyncio
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import zikra.commands as commands
import zikra.db as db
from zikra.commands.log_error import cmd_log_error


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
        err = {'project': 'proj-a', 'runner': 'host1', 'error_type': 'bash',
               'message': "ModuleNotFoundError: No module named 'django'",
               'context_md': 'command: python3 manage.py migrate'}

        r1 = await cmd_log_error(dict(err))
        r2 = await cmd_log_error(dict(err))
        assert 'promoted' not in r1 and 'promoted' not in r2, (r1, r2)

        r3 = await cmd_log_error(dict(err))
        assert r3.get('promoted') is True and r3.get('occurrences') == 3, r3

        async with aio.execute(
            "SELECT title, memory_type, pending_review FROM memories WHERE memory_type='bug'"
        ) as cur:
            bugs = [dict(b) for b in await cur.fetchall()]
        assert len(bugs) == 1, bugs
        assert 'ModuleNotFoundError' in bugs[0]['title']
        assert bugs[0]['pending_review'] == 1

        # A different one-off error does not promote
        r4 = await cmd_log_error({'project': 'proj-a', 'message': 'some other failure'})
        assert 'promoted' not in r4
    finally:
        commands.embed = old_embed
        commands.config.SAVE_DEDUP_ENABLED = old_dedup
        commands.config.PROJECT_RECLASSIFY_ENABLED = old_reclass
        await aio.close()
        db._aio_db = None
        if db._db is not None:
            db._db.close()
            db._db = None


def test_error_promotion_sqlite():
    with tempfile.TemporaryDirectory() as tmpdir:
        asyncio.run(_run(Path(tmpdir) / 'error_promotion.db'))


if __name__ == '__main__':
    test_error_promotion_sqlite()
    print('PASS: test_error_promotion_sqlite')
