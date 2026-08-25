import asyncio
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import zikra.db as db
import zikra.db_postgres as db_postgres
import zikra.embed as embed_mod
import zikra.commands.save_decision as save_decision_mod
import zikra.architecture as architecture_mod
from zikra.commands.save_decision import cmd_save_decision
from zikra.commands.get_architecture import cmd_get_architecture
from zikra.commands.module_history import cmd_module_history
from zikra.commands.sync_state import cmd_get_sync_state, cmd_set_sync_state
from zikra.architecture import architecture_payload, generate_architecture_snapshot
from zikra.db import publish_architecture_snapshot


def test_architecture_ui_exposes_owner_force_regeneration():
    ui = (Path(__file__).resolve().parents[1] / 'ui.html').read_text()
    assert 'id="arch-force-generate"' in ui
    assert 'S.architectureForceEnabled && S.role === \'owner\'' in ui
    assert 'info.architecture_force_enabled === true' in ui
    assert "generateArchitectureDraft(true)" in ui
    assert "generateArchitectureDraft(false)" in ui
    assert "{ project, environment, force }" in ui
    assert 'bypasses the daily generation budget' in ui


def test_force_regeneration_has_default_off_server_gate():
    config_source = (Path(__file__).resolve().parents[1] / 'config.py').read_text()
    server_source = (Path(__file__).resolve().parents[1] / 'server.py').read_text()
    assert "_flag('ZIKRA_ARCHITECTURE_FORCE_ENABLED', '0')" in config_source
    assert 'if force and not config.ARCHITECTURE_FORCE_ENABLED:' in server_source
    assert "'architecture_force_enabled': config.ARCHITECTURE_FORCE_ENABLED" in server_source


def test_architecture_source_redaction():
    text = (
        'api_key: sk-live-secretvalue123456 password=hunter2 service=postgres '
        'DB_PASSWORD=correct-horse KIMI_TOKEN=moon-secret '
        'AWS_SECRET_ACCESS_KEY=aws-secret '
        'Authorization: Bearer abcdefghijklmnopqrstuvwxyz '
        'Proxy-Authorization: Basic dXNlcjpwYXNzd29yZA== '
        'DATABASE_URL=postgres://dbuser:dbpass@db.internal/zikra '
        'direct=postgres://user:pass@host/db '
        '-----BEGIN PRIVATE KEY-----\nprivate-material\n-----END PRIVATE KEY-----'
    )
    redacted = architecture_mod._redact_secrets(text)
    for secret in (
        'secretvalue', 'hunter2', 'correct-horse', 'moon-secret',
        'aws-secret', 'dXNlcjpwYXNzd29yZA', 'dbpass', 'user:pass',
        'private-material',
    ):
        assert secret not in redacted
    assert 'abcdefghijklmnopqrstuvwxyz' not in redacted
    assert 'service=postgres' in redacted
    assert architecture_mod._secret_categories(redacted) == []

    try:
        architecture_mod._assert_no_secrets('DB_PASSWORD=must-never-leave')
        assert False, 'raw sensitive assignments must fail closed'
    except ValueError as exc:
        assert 'must-never-leave' not in str(exc)


def test_postgres_snapshot_json_is_decoded():
    row = {
        'id': 'snapshot-1',
        'document_json': '{"summary":"decoded"}',
        'generated_at': None,
        'published_at': None,
    }
    assert db_postgres._snapshot_pg_dict(row)['document']['summary'] == 'decoded'


async def _reset_sqlite(path):
    if db._aio_db is not None:
        await db._aio_db.close()
    if db._db is not None:
        db._db.close()
    db._aio_db = None
    db._db = None
    db._is_pg = False
    os.environ['DB_BACKEND'] = 'sqlite'
    os.environ['ZIKRA_DB_PATH'] = str(path)

    db.init_db()
    aio = await db.open_aio_db(str(path))
    db.set_aio_db(aio)
    return aio


async def _run_architecture_tests(db_path):
    undo = []
    aio = None
    try:
        old_backend = os.environ.get('DB_BACKEND')
        old_path = os.environ.get('ZIKRA_DB_PATH')
        os.environ['DB_BACKEND'] = 'sqlite'
        os.environ['ZIKRA_DB_PATH'] = str(db_path)
        undo.append(lambda: _restore_env(old_backend, old_path))

        old_embed = save_decision_mod.embed
        vector = [1.0] + [0.0] * 1535

        async def fake_embed(_text):
            return vector

        save_decision_mod.embed = fake_embed
        embed_mod.embed = fake_embed
        undo.append(lambda: _restore_embed(old_embed))

        aio = await _reset_sqlite(db_path)

        # Ordinary product decisions are not architecture decisions. Migration
        # 011 intentionally leaves legacy rows unclassified.
        await aio.execute("""
            INSERT INTO memories
                (id, project, module, memory_type, title, content_md, tags,
                 searchable, status)
            VALUES ('generic-decision', 'veltisai-test', 'product', 'decision',
                    'Ship the beta', 'Product decision only.', '[]', 1, 'current')
        """)
        await aio.commit()
        initial = await cmd_get_architecture({'project': 'veltisai-test'})
        assert initial['count'] == 0

        # 1. save_decision A
        res_a = await cmd_save_decision({
            'project': 'veltisai-test', 'module': 'foresight',
            'title': 'Use Postgres for scoring store',
            'content_md': 'Scoring state lives in Postgres.',
            'evidence': 'src/scoring/store.py:12',
        })
        assert 'id' in res_a, res_a
        id_a = res_a['id']

        # 2. save_decision B superseding A
        res_b = await cmd_save_decision({
            'project': 'veltisai-test', 'module': 'foresight',
            'title': 'Use Redis for scoring store',
            'content_md': 'Scoring state moves to Redis for latency.',
            'environment': 'prod',
            'supersedes_id': id_a,
        })
        id_b = res_b['id']
        assert res_b.get('superseded') == id_a
        assert id_b != id_a

        arch = await cmd_get_architecture({'project': 'veltisai-test'})
        flat = [d for ds in arch['modules'].values() for d in ds]
        assert [d['id'] for d in flat] == [id_b], 'only B should be current'

        hist = await cmd_module_history({'project': 'veltisai-test', 'module': 'foresight'})
        assert [h['id'] for h in hist['history']] == [id_b, id_a]
        assert hist['history'][0]['status'] == 'current'
        assert hist['history'][1]['status'] == 'superseded'

        # 3. strict project scoping
        other = await cmd_get_architecture({'project': 'someone-else'})
        assert other['count'] == 0

        # module filter + environment filter semantics
        by_mod = await cmd_get_architecture({'project': 'veltisai-test', 'module': 'foresight'})
        assert by_mod['count'] == 1 and by_mod['decisions'][0]['id'] == id_b
        prod = await cmd_get_architecture({'project': 'veltisai-test', 'environment': 'prod'})
        assert prod['count'] == 1  # B (prod); env-agnostic rows would also match
        dev = await cmd_get_architecture({'project': 'veltisai-test', 'environment': 'dev'})
        assert dev['count'] == 0

        # Project names are canonicalized for the architecture API.
        canonical = await cmd_get_architecture({'project': 'VeltisAI Test'})
        assert canonical['project'] == 'veltisai-test' and canonical['count'] == 1

        # Supersession is constrained to current architecture decisions in the
        # same project/module; generic memories can never be corrupted.
        bad_prompt = await cmd_save_decision({
            'project': 'veltisai-test', 'module': 'foresight',
            'title': 'Bad target attempt', 'content_md': 'Must fail.',
            'supersedes_id': 'generic-decision',
        })
        assert 'error' in bad_prompt
        async with aio.execute("SELECT status FROM memories WHERE id='generic-decision'") as cur:
            assert (await cur.fetchone())['status'] == 'current'

        missing = await cmd_save_decision({
            'project': 'veltisai-test', 'module': 'foresight',
            'title': 'Missing target attempt', 'content_md': 'Must fail.',
            'supersedes_id': 'does-not-exist',
        })
        assert 'error' in missing

        branch = await cmd_save_decision({
            'project': 'veltisai-test', 'module': 'foresight',
            'title': 'Branch attempt', 'content_md': 'Must fail.',
            'supersedes_id': id_a,
        })
        assert 'error' in branch

        move = await cmd_save_decision({
            'project': 'veltisai-test', 'module': 'another-module',
            'title': 'Use Redis for scoring store',
            'content_md': 'Must not silently move modules.',
        })
        assert 'error' in move

        self_or_rewrite = await cmd_save_decision({
            'project': 'veltisai-test', 'module': 'foresight',
            'title': 'Use Redis for scoring store',
            'content_md': 'Must not rewrite its chain.',
            'supersedes_id': id_b,
        })
        assert 'error' in self_or_rewrite

        # 4. sync-state round-trip
        missing = await cmd_get_sync_state({'project': 'veltisai-test', 'repo_path': '/opt/x'})
        assert missing['status'] == 'not_found'
        await cmd_set_sync_state({'project': 'veltisai-test', 'repo_path': '/opt/x',
                                  'last_synced_commit': 'abc123'})
        got = await cmd_get_sync_state({'project': 'veltisai-test', 'repo_path': '/opt/x'})
        assert got['last_synced_commit'] == 'abc123' and got['status'] == 'ok'
        await cmd_set_sync_state({'project': 'veltisai-test', 'repo_path': '/opt/x',
                                  'last_synced_commit': 'def456'})
        got2 = await cmd_get_sync_state({'project': 'veltisai-test', 'repo_path': '/opt/x'})
        assert got2['last_synced_commit'] == 'def456'
        assert 'error' in await cmd_get_sync_state(
            {'project': 'veltisai-test', 'repo_path': 'relative/path'})

        # 5. re-saving a current title updates content without changing module
        # or the immutable supersession chain.
        res_b2 = await cmd_save_decision({
            'project': 'veltisai-test', 'module': 'foresight',
            'title': 'Use Redis for scoring store',
            'content_md': 'Refined rationale.',
        })
        assert res_b2['id'] == id_b
        hist2 = await cmd_module_history({'project': 'veltisai-test', 'module': 'foresight'})
        assert [h['id'] for h in hist2['history']] == [id_b, id_a]

        # 6. validation errors
        assert 'error' in await cmd_save_decision({'project': 'p', 'title': 'x'})
        assert 'error' in await cmd_save_decision(
            {'project': 'p', 'title': 'x', 'module': 'm', 'environment': 'staging'})
        assert 'error' in await cmd_module_history({'project': 'p'})
        assert 'error' in await cmd_set_sync_state({'project': 'p', 'repo_path': '/x'})
        assert 'error' in await cmd_save_decision(
            {'project': '   ', 'title': 'x', 'module': 'm'})

        return True
    finally:
        for fn in reversed(undo):
            fn()
        if aio is not None:
            await aio.close()
        if db._db is not None:
            db._db.close()
        db._aio_db = None
        db._db = None
        db._is_pg = False


def _restore_env(old_backend, old_path):
    if old_backend is None:
        os.environ.pop('DB_BACKEND', None)
    else:
        os.environ['DB_BACKEND'] = old_backend
    if old_path is None:
        os.environ.pop('ZIKRA_DB_PATH', None)
    else:
        os.environ['ZIKRA_DB_PATH'] = old_path


def _restore_embed(old):
    save_decision_mod.embed = old
    embed_mod.embed = old


def test_architecture_decisions_sqlite():
    with tempfile.TemporaryDirectory() as tmp:
        ok = asyncio.run(_run_architecture_tests(Path(tmp) / 'zikra.db'))
    assert ok


async def _run_snapshot_tests(db_path):
    old_backend = os.environ.get('DB_BACKEND')
    old_path = os.environ.get('ZIKRA_DB_PATH')
    aio = await _reset_sqlite(db_path)
    old_call = architecture_mod._call_model
    try:
        source_id = 'arch-source-1'
        await aio.execute("""
            INSERT INTO memories
                (id, project, memory_type, title, content_md, tags,
                 searchable, status, confidence_score)
            VALUES (?, 'multi-project', 'architecture', 'Current topology',
                    'The API writes to Postgres.', '[]', 1, 'current', 1.0)
        """, [source_id])
        await aio.commit()

        model_calls = 0

        async def fake_call(_content):
            nonlocal model_calls
            model_calls += 1
            return 'kimi-for-coding', '''{
              "summary":"Memory-derived current state.",
              "nodes":[
                {"id":"api","name":"API","kind":"container","parent":null,
                 "description":"Application API","technology":"FastAPI",
                 "status":"current","owner":"platform","confidence":0.9,
                 "evidence":[{"source_id":"arch-source-1","locator":"memory:Current topology","captured_at":"2026-08-16","note":"Explicit topology note"}]},
                {"id":"postgres","name":"Postgres","kind":"store","parent":null,
                 "description":"Durable store","technology":"PostgreSQL",
                 "status":"current","owner":"platform","confidence":0.8,
                 "evidence":[{"source_id":"arch-source-1","locator":"memory:Current topology","captured_at":"2026-08-16","note":"Explicit topology note"}]}
              ],
              "edges":[{"id":"api-postgres","source":"api","target":"postgres","kind":"data","protocol":"SQL","description":"persists records"}],
              "flows":[{"id":"write","name":"Write memory","description":"", "steps":[{"order":1,"source":"api","target":"postgres","label":"insert"}]}],
              "decisions":[], "findings":[],
              "report":{"sections":[{"id":"overview","title":"Overview","content_md":"Evidence-backed report."}]}
            }'''

        architecture_mod._call_model = fake_call
        snapshot = await generate_architecture_snapshot('Multi Project')
        assert snapshot['project'] == 'multi-project'
        assert snapshot['status'] == 'draft'
        assert snapshot['source_count'] == 1
        assert snapshot['evidence_coverage'] == 1.0
        assert len(snapshot['document']['nodes']) == 2
        state = await db.get_architecture_run_state('multi-project')
        assert state['last_status'] == 'success'

        read_only = await architecture_payload('multi-project', include_drafts=False)
        assert read_only['snapshot'] is None
        assert read_only['snapshots'] == []

        payload = await architecture_payload('multi-project')
        assert payload['snapshot']['id'] == snapshot['id']
        assert len(payload['nodes']) == 2 and len(payload['edges']) == 1
        assert payload['report']['sections'][0]['id'] == 'overview'

        published = await publish_architecture_snapshot('multi-project', snapshot['id'])
        assert published['status'] == 'published'
        assert published['published_at']
        visible = await architecture_payload('multi-project', include_drafts=False)
        assert visible['snapshot']['id'] == snapshot['id']

        # On a later local day, unchanged redacted sources reuse the existing
        # snapshot without spending another model call.
        await aio.execute("""
            UPDATE architecture_generation_state
            SET local_run_date = '2000-01-01'
            WHERE project = 'multi-project' AND environment = 'all'
        """)
        await aio.commit()
        unchanged = await generate_architecture_snapshot('multi-project')
        assert unchanged['id'] == snapshot['id'] and model_calls == 1
        unchanged_state = await db.get_architecture_run_state('multi-project')
        assert unchanged_state['last_status'] == 'skipped'

        # Environment is part of generation identity. A dev request may read
        # all as its prior baseline, but must still create a dev-specific draft.
        dev_specific = await generate_architecture_snapshot(
            'multi-project', environment='dev')
        assert dev_specific['environment'] == 'dev'
        assert dev_specific['id'] != snapshot['id'] and model_calls == 2

        # A published snapshot remains visible after more than the UI history
        # window of newer drafts.
        for index in range(31):
            await aio.execute("""
                INSERT INTO architecture_snapshots
                    (id, project, environment, status, document_json, generated_at)
                VALUES (?, 'multi-project', 'all', 'draft', '{}',
                        datetime('now', ?))
            """, [f'newer-draft-{index}', f'+{index + 1} seconds'])
        await aio.execute("""
            INSERT INTO architecture_snapshots
                (id, project, environment, status, document_json, generated_at)
            VALUES ('newer-dev', 'multi-project', 'dev', 'draft', '{}',
                    datetime('now', '+1 day'))
        """)
        await aio.commit()
        still_visible = await architecture_payload(
            'multi-project', environment='all', include_drafts=False)
        assert still_visible['snapshot']['id'] == snapshot['id']
        exact_all = await db.get_architecture_snapshot(
            'multi-project', environment='all')
        assert exact_all['environment'] == 'all'
        dev = await db.get_architecture_snapshot('multi-project', environment='dev')
        assert dev['id'] == 'newer-dev'
        prod_fallback = await db.get_architecture_snapshot(
            'multi-project', environment='prod', status='published')
        assert prod_fallback['id'] == snapshot['id']

        # The DB-backed daily lease prevents duplicate model calls across
        # workers while still allowing an explicit owner force request.
        first_claim = await db.claim_architecture_generation(
            'lease-project', 'all', '2026-08-16', 'digest-a')
        assert first_claim['claimed']
        second_claim = await db.claim_architecture_generation(
            'lease-project', 'all', '2026-08-16', 'digest-a')
        assert not second_claim['claimed'] and second_claim['reason'] == 'running'
        assert await db.finish_architecture_generation(
            'lease-project', 'all', first_claim['attempt_id'], 'success')
        daily_claim = await db.claim_architecture_generation(
            'lease-project', 'all', '2026-08-16', 'digest-b')
        assert not daily_claim['claimed'] and daily_claim['reason'] == 'daily_limit'
        forced_claim = await db.claim_architecture_generation(
            'lease-project', 'all', '2026-08-16', 'digest-b', force=True)
        assert forced_claim['claimed']
        assert await db.finish_architecture_generation(
            'lease-project', 'all', forced_claim['attempt_id'], 'success')

        changes = architecture_mod._document_changes(
            {'nodes': [{'id': 'api', 'name': 'Old API'}]},
            {'nodes': [{'id': 'api', 'name': 'API'}, {'id': 'db', 'name': 'DB'}]},
        )
        assert {c['kind'] for c in changes} == {'added', 'changed'}
    finally:
        architecture_mod._call_model = old_call
        await aio.close()
        if db._db is not None:
            db._db.close()
        db._aio_db = None
        db._db = None
        db._is_pg = False
        _restore_env(old_backend, old_path)


def test_architecture_snapshots_sqlite():
    with tempfile.TemporaryDirectory() as tmp:
        asyncio.run(_run_snapshot_tests(Path(tmp) / 'zikra.db'))
