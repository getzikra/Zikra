"""
MCP server for Zikra — mounts at /mcp on the same FastAPI app.

Transports (primary first):

  Streamable HTTP (MCP spec 2025-03-26) — POST /mcp
      Stateless. No sessions. No in-process state.
      Container restarts are completely invisible to connected clients.
      Use this URL in mcp.json / settings.json:
        http://<host>:<port>/mcp

  SSE (deprecated) — GET /mcp/sse + POST /mcp/messages
      Legacy. Sessions stored in-process; container restart orphans all clients.
      Kept for backwards-compat only. Will be removed in a future release.

mcp.json example:
{
  "mcpServers": {
    "zikra": {
      "url": "http://<host-ip>:8000/mcp",
      "headers": {
        "Authorization": "Bearer <ZIKRA_TOKEN>",
        "X-Zikra-Runner": "<your-hostname>"
      }
    }
  }
}

X-Zikra-Runner identifies the calling host/agent. The server injects it into
tool arguments for `zikra_get_prompt` and `zikra_log_run` so the prompt_id <->
run handshake works automatically (v1.0.6+).
"""

import json
import logging
import re
from contextvars import ContextVar

from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp import types
from starlette.requests import Request
from starlette.responses import Response

from zikra.commands.search import cmd_search
from zikra.commands.save_memory import cmd_save_memory
from zikra.commands.get_prompt import cmd_get_prompt
from zikra.commands.log_run import cmd_log_run
from zikra.commands.log_error import cmd_log_error
from zikra.commands.save_requirement import cmd_save_requirement
from zikra.commands.list_requirements import cmd_list_requirements
from zikra.commands.get_memory import cmd_get_memory
from zikra.commands.get_schema import cmd_get_schema
from zikra.commands.promote_requirement import cmd_promote_requirement
from zikra.commands.create_token import cmd_create_token
from zikra.commands.save_prompt import cmd_save_prompt
from zikra.commands.list_prompts import cmd_list_prompts
from zikra.commands.zikra_help import cmd_zikra_help
from zikra.auth import verify_auth, ROLE_PERMISSIONS
from zikra.version import __version__

logger = logging.getLogger(__name__)

mcp = Server('zikra')
sse_transport = SseServerTransport('/messages')

# Per-connection role — ContextVar (SSE) + session dict (belt-and-suspenders)
_mcp_session_role: ContextVar[str] = ContextVar('_mcp_session_role', default='viewer')
_SESSION_ROLES: dict[str, str] = {}

# v1.0.6: per-connection runner (from X-Zikra-Runner header), injected into
# tool arguments for get_prompt/log_run so the server-side handshake links runs.
_mcp_session_runner: ContextVar[str] = ContextVar('_mcp_session_runner', default='')
_SESSION_RUNNERS: dict[str, str] = {}


async def _check_auth_request(request: Request) -> dict | None:
    """Auth check for Starlette Request. Returns auth_info or None."""
    try:
        return await verify_auth(request)
    except Exception as e:
        logger.warning(f'Auth check error: {e}')
        return None


def _text(data: dict) -> list[types.TextContent]:
    return [types.TextContent(type='text', text=json.dumps(data, ensure_ascii=False))]


# ── Tool registry (single source of truth — used by both transports) ──────────

_TOOLS: list[types.Tool] = [
    types.Tool(
        name='zikra_search',
        description='Search memories using hybrid semantic + keyword search',
        inputSchema={
            'type': 'object',
            'properties': {
                'query': {'type': 'string', 'description': 'Search query'},
                'project': {'type': 'string', 'description': 'Project scope'},
                'limit': {'type': 'integer', 'default': 5},
                'max_tokens': {'type': 'integer', 'default': 2000},
            },
            'required': ['query'],
        },
    ),
    types.Tool(
        name='zikra_save_memory',
        description='Save a new memory or knowledge entry',
        inputSchema={
            'type': 'object',
            'properties': {
                'title': {'type': 'string'},
                'content_md': {'type': 'string'},
                'project': {'type': 'string'},
                'module': {'type': 'string'},
                'memory_type': {'type': 'string', 'default': 'conversation'},
                'tags': {'type': 'array', 'items': {'type': 'string'}},
                'resolution': {'type': 'string'},
                'created_by': {'type': 'string'},
            },
            'required': ['title'],
        },
    ),
    types.Tool(
        name='zikra_get_prompt',
        description='Fetch a saved prompt by name',
        inputSchema={
            'type': 'object',
            'properties': {
                'prompt_name': {'type': 'string'},
                'project': {'type': 'string'},
                'runner': {
                    'type': 'string',
                    'description': 'Hostname/agent identifier (auto-filled by the MCP server from the X-Zikra-Runner header; overriding is optional)',
                },
            },
            'required': ['prompt_name'],
        },
    ),
    types.Tool(
        name='zikra_log_run',
        description='Log a completed prompt run with token usage',
        inputSchema={
            'type': 'object',
            'properties': {
                'project': {'type': 'string'},
                'runner': {'type': 'string'},
                'prompt_name': {'type': 'string'},
                'status': {'type': 'string', 'default': 'success'},
                'output_summary': {'type': 'string'},
                'tokens_input': {'type': 'integer'},
                'tokens_output': {'type': 'integer'},
                'cost_usd': {'type': 'number'},
            },
        },
    ),
    types.Tool(
        name='zikra_log_error',
        description='Log an error or failure event',
        inputSchema={
            'type': 'object',
            'properties': {
                'project': {'type': 'string'},
                'runner': {'type': 'string'},
                'error_type': {'type': 'string'},
                'message': {'type': 'string'},
                'stack_trace': {'type': 'string'},
                'context_md': {'type': 'string'},
            },
        },
    ),
    types.Tool(
        name='zikra_save_requirement',
        description='Save a project requirement (memory_type=requirement)',
        inputSchema={
            'type': 'object',
            'properties': {
                'title': {'type': 'string'},
                'content_md': {'type': 'string'},
                'project': {'type': 'string'},
                'tags': {'type': 'array', 'items': {'type': 'string'}},
            },
            'required': ['title'],
        },
    ),
    types.Tool(
        name='zikra_list_requirements',
        description='List saved requirements, optionally filtered by project or status',
        inputSchema={
            'type': 'object',
            'properties': {
                'project': {'type': 'string'},
                'status': {'type': 'string', 'enum': ['open', 'resolved']},
                'limit': {'type': 'integer', 'default': 50},
            },
        },
    ),
    types.Tool(
        name='zikra_get_memory',
        description='Fetch a memory by title or ID',
        inputSchema={
            'type': 'object',
            'properties': {
                'title': {'type': 'string'},
                'id': {'type': 'string'},
                'memory_type': {'type': 'string'},
            },
        },
    ),
    types.Tool(
        name='zikra_get_schema',
        description='Return the database schema and table definitions',
        inputSchema={'type': 'object', 'properties': {}},
    ),
    types.Tool(
        name='zikra_promote_requirement',
        description='Promote a requirement to a decision or other type',
        inputSchema={
            'type': 'object',
            'properties': {
                'id': {'type': 'string'},
                'title': {'type': 'string'},
                'promote_to': {'type': 'string', 'default': 'decision'},
            },
        },
    ),
    types.Tool(
        name='zikra_create_token',
        description='Generate a new access token',
        inputSchema={
            'type': 'object',
            'properties': {
                'label': {'type': 'string'},
                'role': {'type': 'string', 'default': 'developer'},
            },
        },
    ),
    types.Tool(
        name='zikra_save_prompt',
        description='Save a new prompt with semantic embedding (memory_type=prompt)',
        inputSchema={
            'type': 'object',
            'properties': {
                'title': {'type': 'string'},
                'content_md': {'type': 'string'},
                'project': {'type': 'string'},
                'created_by': {'type': 'string'},
                'tags': {'type': 'array', 'items': {'type': 'string'}},
            },
            'required': ['title'],
        },
    ),
    types.Tool(
        name='zikra_list_prompts',
        description='List all saved prompts, optionally filtered by project',
        inputSchema={
            'type': 'object',
            'properties': {
                'project': {'type': 'string'},
                'limit': {'type': 'integer', 'default': 50},
            },
        },
    ),
    types.Tool(
        name='zikra_help',
        description='Return all available Zikra commands with descriptions and aliases',
        inputSchema={'type': 'object', 'properties': {}},
    ),
]

_MCP_DISPATCH = {
    'zikra_search':               cmd_search,
    'zikra_save_memory':          cmd_save_memory,
    'zikra_get_prompt':           cmd_get_prompt,
    'zikra_log_run':              cmd_log_run,
    'zikra_log_error':            cmd_log_error,
    'zikra_save_requirement':     cmd_save_requirement,
    'zikra_list_requirements':    cmd_list_requirements,
    'zikra_get_memory':           cmd_get_memory,
    'zikra_get_schema':           cmd_get_schema,
    'zikra_promote_requirement':  cmd_promote_requirement,
    'zikra_create_token':         cmd_create_token,
    'zikra_save_prompt':          cmd_save_prompt,
    'zikra_list_prompts':         cmd_list_prompts,
    'zikra_help':                 cmd_zikra_help,
}


async def _run_tool(name: str, arguments: dict, role: str) -> list[types.TextContent]:
    """Auth-check, authorise, and execute a named tool. Used by both transports."""
    command = name.replace('zikra_', '', 1)
    blocked = ROLE_PERMISSIONS.get(role, ROLE_PERMISSIONS['viewer'])
    if command in blocked:
        required = next(
            (r for r, bl in ROLE_PERMISSIONS.items() if command not in bl), 'owner'
        )
        return _text({'error': 'insufficient permissions', 'required_role': required})

    handler = _MCP_DISPATCH.get(name)
    if handler is None:
        return _text({'error': f'Unknown tool: {name}'})

    # v1.0.6: inject runner from X-Zikra-Runner header for the two commands
    # that participate in the prompt_id <-> run handshake. The caller never has
    # to know its own hostname — it comes from the mcp.json headers block.
    runner = _mcp_session_runner.get()
    if runner and name in ('zikra_get_prompt', 'zikra_log_run'):
        if not (arguments or {}).get('runner'):
            arguments = {**(arguments or {}), 'runner': runner}

    try:
        return _text(await handler(arguments))
    except Exception as e:
        logger.exception(f'Tool {name} failed')
        return _text({'error': str(e)})


# ── SSE-compat decorators (keep the mcp.Server happy for the legacy transport) ─

@mcp.list_tools()
async def list_tools() -> list[types.Tool]:
    return _TOOLS


@mcp.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    role = _mcp_session_role.get()
    return await _run_tool(name, arguments, role)


# ── Streamable HTTP transport — MCP spec 2025-03-26 ───────────────────────────

async def _dispatch_rpc(method: str, params: dict, rpc_id, role: str):
    """Route one JSON-RPC 2.0 call. Returns response dict, or None for notifications."""

    if method == 'initialize':
        return {
            'jsonrpc': '2.0', 'id': rpc_id,
            'result': {
                'protocolVersion': '2025-03-26',
                'serverInfo': {'name': 'zikra', 'version': __version__},
                'capabilities': {'tools': {'listChanged': False}},
            },
        }

    if method == 'tools/list':
        return {
            'jsonrpc': '2.0', 'id': rpc_id,
            'result': {
                'tools': [
                    {
                        'name': t.name,
                        'description': t.description or '',
                        'inputSchema': t.inputSchema,
                    }
                    for t in _TOOLS
                ],
            },
        }

    if method == 'tools/call':
        tool_name = params.get('name', '')
        arguments  = params.get('arguments') or {}
        content    = await _run_tool(tool_name, arguments, role)
        return {
            'jsonrpc': '2.0', 'id': rpc_id,
            'result': {
                'content': [{'type': c.type, 'text': c.text} for c in content],
                'isError': False,
            },
        }

    if method == 'ping':
        return {'jsonrpc': '2.0', 'id': rpc_id, 'result': {}}

    if method.startswith('notifications/'):
        return None  # notifications require no response

    return {
        'jsonrpc': '2.0', 'id': rpc_id,
        'error': {'code': -32601, 'message': f'Method not found: {method}'},
    }


async def handle_streamable_http(request: Request) -> Response:
    """
    POST /mcp — Streamable HTTP transport (MCP spec 2025-03-26).
    Stateless: no sessions, no in-process state.
    Container restarts are transparent to all connected clients.

    Called directly as a FastAPI route handler (not via ASGI scope) so that
    Starlette's Mount never issues a 307 redirect on POST /mcp → /mcp/,
    which MCP clients (claude.ai, Cursor) do not follow.
    """
    auth_info = await _check_auth_request(request)
    if not auth_info:
        return Response('Unauthorized', status_code=401)

    role         = auth_info.get('role', 'viewer')
    runner_hdr   = (request.headers.get('X-Zikra-Runner') or '').strip()
    cv_token     = _mcp_session_role.set(role)
    cv_runner    = _mcp_session_runner.set(runner_hdr)

    try:
        body_bytes = await request.body()
        if not body_bytes:
            err = json.dumps({'jsonrpc': '2.0', 'id': None,
                              'error': {'code': -32700, 'message': 'Empty request body'}})
            return Response(err, status_code=400, media_type='application/json')

        rpc    = json.loads(body_bytes)
        method = rpc.get('method', '')
        rpc_id = rpc.get('id')
        params = rpc.get('params') or {}

        result = await _dispatch_rpc(method, params, rpc_id, role)

        if result is None:
            return Response('', status_code=204)
        body = json.dumps(result, ensure_ascii=False)
        return Response(body, media_type='application/json')

    except json.JSONDecodeError:
        err = json.dumps({'jsonrpc': '2.0', 'id': None,
                          'error': {'code': -32700, 'message': 'Parse error'}})
        return Response(err, status_code=400, media_type='application/json')
    except Exception as e:
        logger.exception('Streamable HTTP endpoint error')
        err = json.dumps({'jsonrpc': '2.0', 'id': None,
                          'error': {'code': -32603, 'message': str(e)}})
        return Response(err, status_code=500, media_type='application/json')
    finally:
        _mcp_session_role.reset(cv_token)
        _mcp_session_runner.reset(cv_runner)


async def _streamable_http_endpoint(scope, receive, send):
    """ASGI shim — used by the mounted sub-app only. Delegates to handle_streamable_http."""
    req = Request(scope, receive)
    response = await handle_streamable_http(req)
    await response(scope, receive, send)


# ── SSE transport — deprecated, kept for backwards-compat ─────────────────────

_SID_RE = re.compile(r'session_id=([0-9a-f]+)')


async def _sse_endpoint(scope, receive, send):
    logger.warning(
        'SSE transport is deprecated — migrate MCP clients to POST /mcp '
        '(Streamable HTTP, MCP spec 2025-03-26). /mcp/sse will be removed in a future release.'
    )
    req = Request(scope, receive)
    auth_info = await _check_auth_request(req)
    if not auth_info:
        await Response('Unauthorized', status_code=401)(scope, receive, send)
        return

    role       = auth_info.get('role', 'viewer')
    runner_hdr = (req.headers.get('X-Zikra-Runner') or '').strip()
    session_ids: list[str] = []

    async def _capturing_send(message):
        if message.get('type') == 'http.response.body' and not session_ids:
            body_str = message.get('body', b'').decode('utf-8', errors='replace')
            m = _SID_RE.search(body_str)
            if m:
                sid = m.group(1)
                session_ids.append(sid)
                _SESSION_ROLES[sid] = role
                if runner_hdr:
                    _SESSION_RUNNERS[sid] = runner_hdr
        await send(message)

    cv_token  = _mcp_session_role.set(role)
    cv_runner = _mcp_session_runner.set(runner_hdr)
    try:
        async with sse_transport.connect_sse(scope, receive, _capturing_send) as streams:
            await mcp.run(streams[0], streams[1], mcp.create_initialization_options())
    except Exception as e:
        logger.warning(f'SSE error: {e}')
    finally:
        _mcp_session_role.reset(cv_token)
        _mcp_session_runner.reset(cv_runner)
        for sid in session_ids:
            _SESSION_ROLES.pop(sid, None)
            _SESSION_RUNNERS.pop(sid, None)


async def _messages_endpoint(scope, receive, send):
    from urllib.parse import parse_qs
    req = Request(scope, receive)
    auth_info = await _check_auth_request(req)
    if not auth_info:
        await Response('Unauthorized', status_code=401)(scope, receive, send)
        return

    qs = parse_qs(scope.get('query_string', b'').decode())
    session_id = (qs.get('session_id') or [''])[0]
    role   = _SESSION_ROLES.get(session_id, auth_info.get('role', 'viewer'))
    runner = _SESSION_RUNNERS.get(session_id, (req.headers.get('X-Zikra-Runner') or '').strip())
    cv_token  = _mcp_session_role.set(role)
    cv_runner = _mcp_session_runner.set(runner)
    try:
        await sse_transport.handle_post_message(scope, receive, send)
    finally:
        _mcp_session_role.reset(cv_token)
        _mcp_session_runner.reset(cv_runner)


# ── ASGI router ────────────────────────────────────────────────────────────────

def build_mcp_app():
    """Raw ASGI app routing both transports.

    Uses a flat path router instead of Starlette Mounts to avoid:
    1. Mount('/sse') forcing a 307 trailing-slash redirect that
       MCP clients (Claude.ai, Gemini web) do not follow on SSE.
    2. Mount('/sse') nesting root_path, causing SseServerTransport to
       advertise /mcp/sse/messages instead of /mcp/messages as the POST target.

    Wrapped in CORSMiddleware because mounted ASGI sub-apps sit outside the
    parent FastAPI middleware chain — CORS headers must be applied here directly.
    """
    from starlette.middleware.cors import CORSMiddleware

    async def _inner(scope, receive, send):
        if scope['type'] != 'http':
            return
        path = scope.get('path', '')
        root = scope.get('root_path', '')
        if root and path.startswith(root):
            path = path[len(root):] or '/'

        method = scope.get('method', 'GET').upper()

        # Primary: Streamable HTTP (MCP spec 2025-03-26) — stateless POST
        if path in ('/', '') and method == 'POST':
            await _streamable_http_endpoint(scope, receive, send)

        # Deprecated: SSE legacy transport
        elif path in ('/sse', '/sse/'):
            await _sse_endpoint(scope, receive, send)
        elif path.startswith('/messages'):
            await _messages_endpoint(scope, receive, send)

        else:
            await Response('Not found', status_code=404)(scope, receive, send)

    return CORSMiddleware(
        app=_inner,
        allow_origins=['*'],
        allow_credentials=False,
        allow_methods=['POST', 'GET', 'OPTIONS'],
        allow_headers=['*'],
    )
