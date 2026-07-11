"""Retrieval logging + pin-aware scoring (v1.1.0).

Verifies against a temp SQLite db that:
  - search results bump access_count, set last_accessed_at, and append
    retrievals rows with source='search'
  - get_memory logs a retrieval with source='get'
  - save_memory with pinned=1 persists the pin; re-save without the field
    does not unpin
  - hygiene_report excludes pinned memories
  - scoring applies the pin multiplier and uses last_accessed_at as the
    decay clock
"""

import asyncio
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import zikra.commands as commands
import zikra.db as db
from zikra.commands.search import cmd_search
from zikra.commands.get_memory import cmd_get_memory
from zikra.commands.save_memory import cmd_save_memory
from zikra.scoring import compute_score


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
    import zikra.commands.search as search_mod

    vector = [1.0] + [0.0] * 1535

    async def fake_embed(_text):
        return vector

    old_cmd_embed = commands.embed
    old_search_embed = search_mod.embed
    old_dedup = commands.config.SAVE_DEDUP_ENABLED
    old_reclass = commands.config.PROJECT_RECLASSIFY_ENABLED
    commands.embed = fake_embed
    search_mod.embed = fake_embed
    commands.config.SAVE_DEDUP_ENABLED = False
    commands.config.PROJECT_RECLASSIFY_ENABLED = False
    os.environ['DB_BACKEND'] = 'sqlite'
    os.environ['ZIKRA_DB_PATH'] = str(db_path)
    aio = await _reset_sqlite(db_path)

    try:
        saved = await cmd_save_memory({
            'title': 'retrieval target', 'content_md': 'about deploy pipelines',
            'project': 'proj-a', 'memory_type': 'decision',
        })
        assert saved['status'] == 'saved', saved
        mem_id = saved['id']

        # search → retrieval logged, access bumped, decay clock set
        res = await cmd_search({'query': 'deploy pipelines', 'project': 'proj-a'})
        assert any(r['id'] == mem_id for r in res['results']), res

        async with aio.execute(
            "SELECT access_count, last_accessed_at, pinned FROM memories WHERE id=?", [mem_id]
        ) as cur:
            row = await cur.fetchone()
        assert row['access_count'] == 1, dict(row)
        assert row['last_accessed_at'] is not None, dict(row)

        async with aio.execute(
            "SELECT source, query FROM retrievals WHERE memory_id=?", [mem_id]
        ) as cur:
            hits = await cur.fetchall()
        assert len(hits) == 1 and hits[0]['source'] == 'search', [dict(h) for h in hits]
        assert hits[0]['query'] == 'deploy pipelines'

        # get_memory → second retrieval, source='get'
        got = await cmd_get_memory({'id': mem_id})
        assert got['title'] == 'retrieval target'
        async with aio.execute(
            "SELECT COUNT(*) AS n FROM retrievals WHERE memory_id=? AND source='get'", [mem_id]
        ) as cur:
            n = (await cur.fetchone())['n']
        assert n == 1

        # pin persists; re-save without the field does not unpin
        await cmd_save_memory({
            'title': 'retrieval target', 'content_md': 'about deploy pipelines',
            'project': 'proj-a', 'memory_type': 'decision', 'pinned': 1,
        })
        await cmd_save_memory({
            'title': 'retrieval target', 'content_md': 'edited content',
            'project': 'proj-a', 'memory_type': 'decision',
        })
        async with aio.execute(
            "SELECT pinned FROM memories WHERE id=?", [mem_id]
        ) as cur:
            assert (await cur.fetchone())['pinned'] == 1

        # hygiene excludes pinned: backdate the pinned memory + an unpinned one
        await cmd_save_memory({
            'title': 'stale orphan', 'content_md': 'old and unlinked',
            'project': 'proj-a', 'memory_type': 'note',
        })
        await aio.execute(
            "UPDATE memories SET created_at=datetime('now','-120 days'), "
            "updated_at=datetime('now','-120 days'), last_accessed_at=NULL"
        )
        await aio.commit()
        from zikra.commands.hygiene import cmd_hygiene
        rep = await cmd_hygiene({'project': 'proj-a', 'stale_days': 30})
        titles = [m['title'] for m in rep['memories']]
        assert 'stale orphan' in titles, rep
        assert 'retrieval target' not in titles, rep

        # scoring: pin multiplier + last_accessed_at resets the decay clock
        old_date = (datetime.now(timezone.utc) - timedelta(days=120)).isoformat()
        base = {'created_at': old_date, 'access_count': 0, 'confidence_score': 1.0}
        stale = compute_score(base)
        pinned = compute_score({**base, 'pinned': 1})
        refreshed = compute_score({**base, 'last_accessed_at': datetime.now(timezone.utc).isoformat()})
        assert pinned > stale
        assert refreshed > stale
        assert refreshed >= 0.9, refreshed
    finally:
        commands.embed = old_cmd_embed
        search_mod.embed = old_search_embed
        commands.config.SAVE_DEDUP_ENABLED = old_dedup
        commands.config.PROJECT_RECLASSIFY_ENABLED = old_reclass
        await aio.close()
        db._aio_db = None
        if db._db is not None:
            db._db.close()
            db._db = None


def test_retrieval_scoring_sqlite():
    with tempfile.TemporaryDirectory() as tmpdir:
        asyncio.run(_run(Path(tmpdir) / 'retrieval_scoring.db'))


if __name__ == '__main__':
    test_retrieval_scoring_sqlite()
    print('PASS: test_retrieval_scoring_sqlite')
