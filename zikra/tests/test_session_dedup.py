"""Session-level run dedup (v1.1.0).

Two log_run calls with the same (runner, session_id) — e.g. the Stop hook and
the watcher daemon — must converge on ONE prompt_runs row, keeping the higher
token counts and the longer output_summary. Runs without a session_id keep
the old insert-always behavior.
"""

import asyncio
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import zikra.db as db
from zikra.commands.log_run import cmd_log_run


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
    aio = await _reset_sqlite(db_path)
    try:
        diary = 'A long, rich diary of what actually happened this session.' * 3

        # Stop hook fires first with the diary
        r1 = await cmd_log_run({
            'project': 'proj-a', 'runner': 'host1', 'session_id': 'sess-123',
            'output_summary': diary,
            'tokens_input': 100, 'tokens_output': 50,
        })
        assert r1['status'] == 'logged'

        # Watcher fires later: thinner summary, higher totals
        r2 = await cmd_log_run({
            'project': 'proj-a', 'runner': 'host1', 'session_id': 'sess-123',
            'output_summary': 'Session ended',
            'tokens_input': 120, 'tokens_output': 60,
        })
        assert r2['id'] == r1['id'], (r1, r2)
        assert r2.get('deduped') is True, r2

        async with aio.execute(
            "SELECT COUNT(*) AS n FROM prompt_runs WHERE session_id='sess-123'"
        ) as cur:
            assert (await cur.fetchone())['n'] == 1

        async with aio.execute(
            "SELECT output_summary, tokens_input, tokens_output FROM prompt_runs WHERE id=?",
            [r1['id']]
        ) as cur:
            row = await cur.fetchone()
        assert row['output_summary'] == diary  # longer summary wins
        assert row['tokens_input'] == 120 and row['tokens_output'] == 60

        # Same session on a DIFFERENT runner → separate row
        r3 = await cmd_log_run({
            'project': 'proj-a', 'runner': 'host2', 'session_id': 'sess-123',
            'output_summary': 'other machine',
        })
        assert r3['id'] != r1['id']

        # No session_id → always a new row
        r4 = await cmd_log_run({'project': 'proj-a', 'runner': 'host1', 'output_summary': 'x'})
        r5 = await cmd_log_run({'project': 'proj-a', 'runner': 'host1', 'output_summary': 'x'})
        assert r4['id'] != r5['id']
    finally:
        await aio.close()
        db._aio_db = None
        if db._db is not None:
            db._db.close()
            db._db = None


def test_session_dedup_sqlite():
    with tempfile.TemporaryDirectory() as tmpdir:
        asyncio.run(_run(Path(tmpdir) / 'session_dedup.db'))


if __name__ == '__main__':
    test_session_dedup_sqlite()
    print('PASS: test_session_dedup_sqlite')
