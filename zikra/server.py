import logging
import os
from contextlib import asynccontextmanager
from json import JSONDecodeError
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from dotenv import load_dotenv

from zikra.db import (
    debug_memory_count,
    init_db,
    is_postgres,
    list_all_memories,
    list_projects,
    list_by_memory_type,
    open_aio_db,
    set_aio_db,
)
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
from zikra.commands.version import cmd_version
from zikra.mcp_server import build_mcp_app
from zikra.version import __version__

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


app = FastAPI(title='Zikra', version=__version__, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_credentials=False,
    allow_methods=['*'],
    allow_headers=['*'],
)
app.mount('/mcp', build_mcp_app())


# ── Minimum role required per command ─────────────────────────────────────────

COMMAND_MIN_ROLE = {
    'search':               'viewer',
    'get_memory':           'viewer',
    'get_prompt':           'viewer',
    'list_prompts':         'viewer',
    'list_requirements':    'viewer',
    'zikra_help':           'viewer',
    'version':              'viewer',
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
        'version':        __version__,
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
    'version':              cmd_version,
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
    # version aliases
    'ver':                  cmd_version,
    'server_version':       cmd_version,
}

# Canonical command names (derived from DISPATCH, no aliases) for error messages
KNOWN_COMMANDS = sorted(set(COMMAND_MIN_ROLE.keys()))


# ── GitHub version cache ───────────────────────────────────────────────────────

_github_version_cache: dict = {'version': None, 'checked': ''}


async def _get_latest_github_version() -> str | None:
    import datetime
    today = datetime.date.today().isoformat()
    if _github_version_cache['checked'] == today and _github_version_cache['version']:
        return _github_version_cache['version']
    try:
        import urllib.request
        import json as _json
        req = urllib.request.Request(
            'https://api.github.com/repos/getzikra/zikra/tags',
            headers={'User-Agent': f'zikra-server/{__version__}'},
        )
        resp = urllib.request.urlopen(req, timeout=5)
        tags = _json.loads(resp.read().decode())
        if tags and isinstance(tags, list) and 'name' in tags[0]:
            _github_version_cache['version'] = tags[0]['name'].lstrip('v')
        _github_version_cache['checked'] = today
    except Exception:
        pass
    return _github_version_cache['version']


# ── Health ─────────────────────────────────────────────────────────────────────

@app.get('/health')
async def health():
    latest = await _get_latest_github_version()
    result = {
        'status':  'ok',
        'version': __version__,
        'backend': os.getenv('DB_BACKEND', 'sqlite'),
    }
    if latest:
        result['latest_version'] = latest
    return result


# ── Web UI ─────────────────────────────────────────────────────────────────────

_UI_HTML = (Path(__file__).with_name('ui.html')).read_text(encoding='utf-8')


@app.get('/', response_class=HTMLResponse)
async def web_ui():
    return HTMLResponse(_UI_HTML)


def _normalise_title(value: str) -> str:
    return ' '.join((value or '').lower().split())


def _build_graph_payload(memories: list[dict]) -> dict:
    max_edges = 260
    node_degree_cap = 6
    title_map = {m['id']: _normalise_title(m.get('title', '')) for m in memories}
    candidate_edges: list[tuple[float, str, str, str]] = []
    ids = [m['id'] for m in memories]

    for index, left in enumerate(memories):
        left_title = title_map[left['id']]
        left_content = (left.get('content_md') or '').lower()
        left_tags = {str(tag).strip().lower() for tag in (left.get('tags') or []) if str(tag).strip()}
        for right in memories[index + 1:]:
            right_title = title_map[right['id']]
            right_content = (right.get('content_md') or '').lower()
            right_tags = {str(tag).strip().lower() for tag in (right.get('tags') or []) if str(tag).strip()}

            score = 0.0
            relation = ''
            shared_tags = left_tags & right_tags
            if left.get('module') and left.get('module') == right.get('module'):
                score += 2.4
                relation = 'module'
            if shared_tags:
                score += min(1.8, 0.7 * len(shared_tags))
                relation = relation or 'tag'
            if left.get('project') and left.get('project') == right.get('project'):
                score += 1.85
                relation = relation or 'project'
            if left_title and len(left_title) >= 10 and left_title in right_content:
                score += 3.2
                relation = 'reference'
            if right_title and len(right_title) >= 10 and right_title in left_content:
                score += 3.2
                relation = 'reference'
            if left.get('memory_type') == right.get('memory_type'):
                score += 0.25
            if score >= 2.0:
                candidate_edges.append((score, left['id'], right['id'], relation or 'related'))

    candidate_edges.sort(key=lambda item: item[0], reverse=True)
    degree_count = {node_id: 0 for node_id in ids}
    edges = []
    for score, source, target, relation in candidate_edges:
        if len(edges) >= max_edges:
            break
        if degree_count[source] >= node_degree_cap or degree_count[target] >= node_degree_cap:
            continue
        degree_count[source] += 1
        degree_count[target] += 1
        edges.append({
            'source': source,
            'target': target,
            'type': relation,
            'weight': round(score, 2),
        })

    nodes = []
    for memory in memories:
        nodes.append({
            'id': memory['id'],
            'title': memory.get('title') or 'Untitled',
            'snippet': memory.get('snippet') or '',
            'memory_type': memory.get('memory_type') or 'conversation',
            'project': memory.get('project') or 'global',
            'module': memory.get('module') or '',
            'created_at': memory.get('created_at'),
            'access_count': memory.get('access_count') or 0,
            'created_by': memory.get('created_by') or '',
        })
    return {'nodes': nodes, 'edges': edges}


@app.get('/api/ui/bootstrap')
async def ui_bootstrap(request: Request):
    auth_info = await verify_auth(request)
    project = request.query_params.get('project') or 'global'
    prompts = await list_by_memory_type('prompt', project, 8)
    requirements = await list_by_memory_type('requirement', project, 8)
    return {
        'role': auth_info.get('role', 'viewer'),
        'project': project,
        'projects': await list_projects(),
        'memory_total': await debug_memory_count(),
        'recent_prompts': prompts,
        'recent_requirements': requirements,
    }


@app.get('/api/ui/graph')
async def ui_graph(request: Request):
    await verify_auth(request)
    project = request.query_params.get('project') or 'global'
    limit = min(int(request.query_params.get('limit', '180')), 300)
    memories = await list_all_memories(project, limit)
    return _build_graph_payload(memories)


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
    command = str(body.get('command') or '').lower().strip()
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
        display = command[:100] + '...' if len(command) > 100 else command
        help_data = await cmd_zikra_help(body)
        return JSONResponse(
            status_code=400,
            content={
                'error': f'Unknown command: {display!r}',
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
