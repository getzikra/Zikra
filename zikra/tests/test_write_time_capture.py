import asyncio
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import zikra.commands as commands
import zikra.db as db
import zikra.embed as embed_mod


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


def _setattr(obj, name, value, undo):
    old = getattr(obj, name)
    setattr(obj, name, value)
    undo.append(lambda: setattr(obj, name, old))


def _setenv(name, value, undo):
    old = os.environ.get(name)
    os.environ[name] = value
    if old is None:
        undo.append(lambda: os.environ.pop(name, None))
    else:
        undo.append(lambda: os.environ.__setitem__(name, old))


async def _run_write_time_capture_sqlite(db_path):
    undo = []
    aio = None
    try:
        _setenv('DB_BACKEND', 'sqlite', undo)
        _setenv('ZIKRA_DB_PATH', str(db_path), undo)
        aio = await _reset_sqlite(db_path)

        vector = [1.0] + [0.0] * 1535

        async def fake_embed(_text):
            return vector

        _setattr(commands, 'embed', fake_embed, undo)
        _setattr(embed_mod, 'embed', fake_embed, undo)
        _setattr(commands.config, 'PROJECT_RECLASSIFY_ENABLED', True, undo)
        _setattr(commands.config, 'SAVE_DEDUP_ENABLED', True, undo)
        _setattr(commands.config, 'SAVE_DEDUP_SIM_THRESHOLD', 0.90, undo)
        _setattr(commands.config, 'SAVE_DEDUP_WINDOW_MIN', 45, undo)

        first_id, degraded = await commands._embed_and_store({
            'project': 'alpha',
            'memory_type': 'conversation',
            'title': 'Conversation one',
            'content_md': 'body one',
            'created_by': 'tester',
        }, 'Conversation one')
        assert degraded is False

        second_id, degraded = await commands._embed_and_store({
            'project': 'alpha',
            'memory_type': 'conversation',
            'title': 'Conversation two',
            'content_md': 'body two',
            'created_by': 'tester',
        }, 'Conversation two')
        assert degraded is False
        assert second_id == first_id

        async with aio.execute(
            """SELECT COUNT(*) AS n, MAX(content_md) AS content_md
               FROM memories
               WHERE project = 'alpha'
                 AND memory_type = 'conversation'
                 AND created_by = 'tester'"""
        ) as cur:
            row = await cur.fetchone()
        assert row['n'] == 1
        assert row['content_md'] == 'body two'

        decision_id, degraded = await commands._embed_and_store({
            'project': 'alpha',
            'memory_type': 'decision',
            'title': 'Decision one',
            'content_md': 'body two',
            'created_by': 'tester',
        }, 'Decision one')
        assert degraded is False
        assert decision_id != first_id

        async with aio.execute(
            "SELECT COUNT(*) AS n FROM memories WHERE project = 'alpha' AND created_by = 'tester'"
        ) as cur:
            row = await cur.fetchone()
        assert row['n'] == 2

        async def agreed_neighbors(_embedding, _k):
            return [
                {'project': 'majority', 'sim': 0.91},
                {'project': 'majority', 'sim': 0.89},
                {'project': 'majority', 'sim': 0.88},
                {'project': 'other', 'sim': 0.87},
            ]

        _setattr(commands, 'nearest_projects', agreed_neighbors, undo)
        _setattr(commands.config, 'PROJECT_RECLASSIFY_MIN_SIM', 0.55, undo)
        _setattr(commands.config, 'PROJECT_RECLASSIFY_MIN_AGREE', 0.6, undo)
        _setattr(commands.config, 'PROJECT_RECLASSIFY_MIN_VOTES', 3, undo)
        assert await commands._vote_project(vector, 'current') == 'majority'

        _setattr(commands.config, 'PROJECT_RECLASSIFY_MIN_SIM', 0.95, undo)
        assert await commands._vote_project(vector, 'current') is None
    finally:
        for restore in reversed(undo):
            restore()
        if aio is not None:
            await aio.close()
        db._aio_db = None
        if db._db is not None:
            db._db.close()
            db._db = None
        db._is_pg = False


def test_write_time_capture_sqlite():
    with tempfile.TemporaryDirectory() as tmpdir:
        asyncio.run(_run_write_time_capture_sqlite(Path(tmpdir) / 'write_time_capture.db'))


if __name__ == '__main__':
    test_write_time_capture_sqlite()
    print('PASS: test_write_time_capture_sqlite')
