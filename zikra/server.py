import logging
import os
from contextlib import asynccontextmanager
from json import JSONDecodeError

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from dotenv import load_dotenv

from zikra.db import init_db, is_postgres, debug_memory_count, open_aio_db, set_aio_db
from zikra.auth import verify_auth, ROLE_PERMISSIONS
from zikra.commands.search import cmd_search
from zikra.commands.save_memory import cmd_save_memory
from zikra.commands.get_prompt import cmd_get_prompt
from zikra.commands.get_memory import cmd_get_memory
from zikra.commands.log_run import cmd_log_run
from zikra.commands.log_error import cmd_log_error
from zikra.commands.get_schema import cmd_get_schema
from zikra.commands.save_requirement import cmd_save_requirement
from zikra.commands.list_requirements import cmd_list_requirements
from zikra.commands.promote_requirement import cmd_promote_requirement
from zikra.commands.create_token import cmd_create_token
from zikra.commands.save_prompt import cmd_save_prompt
from zikra.commands.list_prompts import cmd_list_prompts
from zikra.commands.zikra_help import cmd_zikra_help
from zikra.mcp_server import build_mcp_app

logger = logging.getLogger(__name__)

load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    backend = os.getenv('DB_BACKEND', 'sqlite').lower()
    if backend == 'sqlite':
        db_path = os.getenv('ZIKRA_DB_PATH', './zikra.db')
        db_conn = await open_aio_db(db_path)
        set_aio_db(db_conn)
        app.state.sqlite_db = db_conn
    elif backend == 'postgres':
        from zikra.db_postgres import init_pg
        await init_pg()
    host = os.getenv('ZIKRA_HOST', '0.0.0.0')
    port = os.getenv('ZIKRA_PORT', '8000')
    logger.info(f'Zikra running at http://{host}:{port}/webhook/zikra (backend: {backend})')
    yield
    if backend == 'sqlite' and hasattr(app.state, 'sqlite_db'):
        await app.state.sqlite_db.close()


app = FastAPI(title='Zikra Lite', version='0.1.0', lifespan=lifespan)
app.mount('/mcp', build_mcp_app())


# ── Minimum role required per command ─────────────────────────────────────────

COMMAND_MIN_ROLE = {
    'search':               'viewer',
    'get_memory':           'viewer',
    'get_prompt':           'viewer',
    'list_prompts':         'viewer',
    'list_requirements':    'viewer',
    'zikra_help':           'viewer',
    'save_memory':          'developer',
    'save_prompt':          'developer',
    'save_requirement':     'developer',
    'promote_requirement':  'developer',
    'log_run':              'developer',
    'log_error':            'developer',
    'get_schema':           'admin',
    'debug_protocol':       'admin',
    'create_token':         'owner',
}


# ── debug_protocol handler (inline — no separate file needed) ─────────────────

async def _cmd_debug_protocol(_body: dict) -> dict:
    count = await debug_memory_count()
    return {
        'backend':        'postgres' if is_postgres() else 'sqlite',
        'db_path':        os.getenv('ZIKRA_DB_PATH', './zikra.db') if not is_postgres() else None,
        'memory_count':   count,
        'openai_key_set': bool(os.getenv('OPENAI_API_KEY')),
        'version':        '0.1',
    }


# ── Single dispatch table: canonical names + all aliases ──────────────────────

DISPATCH: dict = {
    # canonical
    'search':               cmd_search,
    'save_memory':          cmd_save_memory,
    'get_prompt':           cmd_get_prompt,
    'get_memory':           cmd_get_memory,
    'log_run':              cmd_log_run,
    'log_error':            cmd_log_error,
    'get_schema':           cmd_get_schema,
    'save_requirement':     cmd_save_requirement,
    'list_requirements':    cmd_list_requirements,
    'promote_requirement':  cmd_promote_requirement,
    'create_token':         cmd_create_token,
    'save_prompt':          cmd_save_prompt,
    'list_prompts':         cmd_list_prompts,
    'zikra_help':           cmd_zikra_help,
    'debug_protocol':       _cmd_debug_protocol,
    # search aliases
    'find':                 cmd_search,
    'query':                cmd_search,
    'recall':               cmd_search,
    'lookup':               cmd_search,
    'search_memory':        cmd_search,
    'find_memory':          cmd_search,
    'retrieve':             cmd_search,
    'remember':             cmd_search,
    # save_memory aliases
    'save':                 cmd_save_memory,
    'store':                cmd_save_memory,
    'write_memory':         cmd_save_memory,
    'add_memory':           cmd_save_memory,
    'write':                cmd_save_memory,
    # get_prompt aliases
    'run_prompt':           cmd_get_prompt,
    'fetch_prompt':         cmd_get_prompt,
    'load_prompt':          cmd_get_prompt,
    'execute_prompt':       cmd_get_prompt,
    # get_memory aliases
    'fetch_memory':         cmd_get_memory,
    'read_memory':          cmd_get_memory,
    'load_memory':          cmd_get_memory,
    # log_run aliases
    'log_session':          cmd_log_run,
    'end_session':          cmd_log_run,
    'finish_run':           cmd_log_run,
    'log_completion':       cmd_log_run,
    # log_error aliases
    'log_bug':              cmd_log_error,
    'report_error':         cmd_log_error,
    'save_error':           cmd_log_error,
    'log_failure':          cmd_log_error,
    # get_schema aliases
    'schema':               cmd_get_schema,
    'get_db':               cmd_get_schema,
    # debug_protocol aliases
    'debug':                _cmd_debug_protocol,
    'dp':                   _cmd_debug_protocol,
    # list aliases
    'list_reqs':            cmd_list_requirements,
    'get_requirements':     cmd_list_requirements,
    'get_prompts':          cmd_list_prompts,
    # promote aliases
    'promote':              cmd_promote_requirement,
    # create_token aliases
    'new_token':            cmd_create_token,
    'token':                cmd_create_token,
    # save_prompt aliases
    'write_prompt':         cmd_save_prompt,
    'store_prompt':         cmd_save_prompt,
    # zikra_help aliases
    'help':                 cmd_zikra_help,
}

# Canonical command names (derived from DISPATCH, no aliases) for error messages
KNOWN_COMMANDS = sorted(set(COMMAND_MIN_ROLE.keys()))


# ── Health ─────────────────────────────────────────────────────────────────────

@app.get('/health')
async def health():
    return {
        'status':  'ok',
        'version': '1.0',
        'backend': os.getenv('DB_BACKEND', 'sqlite'),
    }


# ── Web UI ─────────────────────────────────────────────────────────────────────

_UI_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Zikra Lite</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         background: #0f1117; color: #e2e8f0; min-height: 100vh; padding: 2rem; }
  h1 { font-size: 1.5rem; font-weight: 700; color: #a78bfa; margin-bottom: 0.25rem; }
  .sub { color: #64748b; font-size: 0.875rem; margin-bottom: 2rem; }
  .stats { display: flex; gap: 1.5rem; margin-bottom: 2rem; flex-wrap: wrap; }
  .stat { background: #1e2130; border: 1px solid #2d3148; border-radius: 8px;
          padding: 1rem 1.5rem; min-width: 120px; }
  .stat-n { font-size: 1.75rem; font-weight: 700; color: #a78bfa; }
  .stat-l { font-size: 0.75rem; color: #64748b; margin-top: 0.25rem; }
  .search-row { display: flex; gap: 0.75rem; margin-bottom: 1.5rem; flex-wrap: wrap; }
  input, select { background: #1e2130; border: 1px solid #2d3148; color: #e2e8f0;
                  border-radius: 6px; padding: 0.5rem 0.75rem; font-size: 0.875rem; }
  input[type=text] { flex: 1; min-width: 200px; }
  input[type=password] { width: 220px; }
  button { background: #7c3aed; color: #fff; border: none; border-radius: 6px;
           padding: 0.5rem 1.25rem; cursor: pointer; font-size: 0.875rem; }
  button:hover { background: #6d28d9; }
  .results { display: flex; flex-direction: column; gap: 0.75rem; }
  .card { background: #1e2130; border: 1px solid #2d3148; border-radius: 8px; padding: 1rem; }
  .card-title { font-weight: 600; color: #c4b5fd; margin-bottom: 0.4rem; }
  .card-snippet { font-size: 0.8rem; color: #94a3b8; line-height: 1.5; }
  .card-meta { font-size: 0.7rem; color: #475569; margin-top: 0.5rem; }
  .badge { display: inline-block; background: #312e81; color: #a5b4fc;
           border-radius: 4px; padding: 0.1rem 0.4rem; font-size: 0.65rem;
           margin-right: 0.35rem; }
  .msg { color: #64748b; font-size: 0.875rem; padding: 1rem 0; }
  .err { color: #f87171; font-size: 0.875rem; padding: 0.5rem 0; }
</style>
</head>
<body>
<h1>Zikra Lite</h1>
<p class="sub">Local AI memory — <span id="host"></span></p>

<div class="stats" id="stats">
  <div class="stat"><div class="stat-n" id="s-total">—</div><div class="stat-l">memories</div></div>
  <div class="stat"><div class="stat-n" id="s-prompts">—</div><div class="stat-l">prompts</div></div>
  <div class="stat"><div class="stat-n" id="s-reqs">—</div><div class="stat-l">requirements</div></div>
</div>

<div class="search-row">
  <input type="password" id="tok" placeholder="Bearer token" />
  <input type="text" id="q" placeholder="Search memories…" />
  <select id="proj"><option value="">all projects</option></select>
  <button onclick="doSearch()">Search</button>
</div>
<div id="err" class="err"></div>
<div class="results" id="results"><p class="msg">Enter your token and a query to search.</p></div>

<script>
document.getElementById('host').textContent = location.host;

const tok = () => document.getElementById('tok').value.trim();

async function api(command, extra = {}) {
  const t = tok();
  if (!t) { document.getElementById('err').textContent = 'Token required'; return null; }
  document.getElementById('err').textContent = '';
  const r = await fetch('/webhook/zikra', {
    method: 'POST',
    headers: { 'Authorization': 'Bearer ' + t, 'Content-Type': 'application/json' },
    body: JSON.stringify({ command, ...extra })
  });
  if (r.status === 401) { document.getElementById('err').textContent = 'Bad token'; return null; }
  return r.json();
}

async function loadStats() {
  const t = tok();
  if (!t) return;
  const r = await api('get_schema');
  if (!r) return;
  document.getElementById('s-total').textContent = '✓';
}

async function doSearch() {
  const q = document.getElementById('q').value.trim();
  const proj = document.getElementById('proj').value || 'global';
  if (!q) return;
  const r = await api('search', { query: q, project: proj, limit: 10 });
  if (!r) return;
  const el = document.getElementById('results');
  if (!r.results || r.results.length === 0) {
    el.innerHTML = '<p class="msg">No results found.</p>'; return;
  }
  el.innerHTML = r.results.map(m => `
    <div class="card">
      <div class="card-title">${esc(m.title)}</div>
      <div class="card-snippet">${esc(m.snippet || '')}</div>
      <div class="card-meta">
        <span class="badge">${esc(m.memory_type)}</span>
        <span class="badge">${esc(m.project)}</span>
        score: ${m.score} &nbsp; ${m.created_at || ''}
      </div>
    </div>`).join('');
}

function esc(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

document.getElementById('q').addEventListener('keydown', e => { if (e.key === 'Enter') doSearch(); });
document.getElementById('tok').addEventListener('change', loadStats);
</script>
</body>
</html>"""


@app.get('/', response_class=HTMLResponse)
async def web_ui():
    return HTMLResponse(_UI_HTML)


# ── Webhook ────────────────────────────────────────────────────────────────────

@app.post('/webhook/zikra')
async def handle(request: Request):
    auth_info = await verify_auth(request)
    try:
        body = await request.json()
    except (JSONDecodeError, Exception):
        return JSONResponse(
            status_code=400,
            content={'error': 'Request body is not valid JSON'},
        )
    command = body.get('command', '').lower().strip()
    handler = DISPATCH.get(command)

    # Resolve alias to canonical name for permission check
    canonical = command
    for name, fn in DISPATCH.items():
        if fn is handler and name in COMMAND_MIN_ROLE:
            canonical = name
            break

    caller_role = auth_info.get('role', 'viewer')
    blocked = ROLE_PERMISSIONS.get(caller_role, ROLE_PERMISSIONS['viewer'])
    if canonical in blocked:
        required = COMMAND_MIN_ROLE.get(canonical, 'owner')
        return JSONResponse(
            status_code=403,
            content={'error': 'insufficient permissions', 'required_role': required},
        )

    if handler is None:
        help_data = await cmd_zikra_help(body)
        return JSONResponse(
            status_code=400,
            content={
                'error': f'Unknown command: {command!r}',
                'hint': 'Send {"command": "zikra_help"} for the full reference.',
                'available_commands': KNOWN_COMMANDS,
                'commands': help_data['commands'],
            },
        )

    result = await handler(body)
    result['_use_command'] = canonical
    if command != canonical:
        result['_was_alias'] = True
        result['_raw_command'] = command
    return result
