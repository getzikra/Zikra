"""
MCP server for Zikra Lite — mounts at /mcp on the same FastAPI app.
SSE endpoint: GET  /mcp/sse
Messages:     POST /mcp/messages

mcp.json for teammates:
{
  "mcpServers": {
    "zikra": {
      "url": "http://<host-ip>:8000/mcp/sse",
      "headers": { "Authorization": "Bearer <ZIKRA_TOKEN>" }
    }
  }
}
"""

import json
import logging
import re
from contextvars import ContextVar

from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp import types
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Mount, Route

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

logger = logging.getLogger(__name__)

mcp = Server('zikra')
sse_transport = SseServerTransport('/messages')

# Per-connection role: ContextVar (works when call_tool runs in SSE context)
# + session dict (belt-and-suspenders for POST handler context)
_mcp_session_role: ContextVar[str] = ContextVar('_mcp_session_role', default='viewer')
_SESSION_ROLES: dict[str, str] = {}


async def _check_auth_request(request: Request) -> dict | None:
    """Auth check for Starlette Request objects. Returns auth_info dict or None."""
    try:
        return await verify_auth(request)
    except Exception as e:
        logger.warning(f'Auth check error: {e}')
        return None


def _text(data: dict) -> list[types.TextContent]:
    return [types.TextContent(type='text', text=json.dumps(data, ensure_ascii=False))]


# ── Tool definitions ───────────────────────────────────────────────────────────

@mcp.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
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
                    'role': {'type': 'string', 'default': 'admin'},
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


# ── Tool dispatch ──────────────────────────────────────────────────────────────

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


@mcp.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    command = name.replace('zikra_', '', 1)
    caller_role = _mcp_session_role.get()
    blocked = ROLE_PERMISSIONS.get(caller_role, ROLE_PERMISSIONS['viewer'])
    if command in blocked:
        required = next(
            role for role, bl in ROLE_PERMISSIONS.items() if command not in bl
        )
        return _text({'error': 'insufficient permissions', 'required_role': required})

    handler = _MCP_DISPATCH.get(name)
    if handler is None:
        return _text({'error': f'Unknown tool: {name}'})

    try:
        return _text(await handler(arguments))
    except Exception as e:
        logger.exception(f'Tool {name} failed')
        return _text({'error': str(e)})


# ── ASGI endpoints ─────────────────────────────────────────────────────────────

_SID_RE = re.compile(r'session_id=([0-9a-f]+)')


async def _sse_endpoint(request: Request) -> None:
    auth_info = await _check_auth_request(request)
    if not auth_info:
        return Response('Unauthorized', status_code=401)

    role = auth_info.get('role', 'viewer')
    session_ids: list[str] = []

    # Intercept the SSE send to capture the session_id from the endpoint event,
    # then store the role in _SESSION_ROLES so _messages_endpoint can look it up.
    orig_send = request._send

    async def _capturing_send(message):
        if message.get('type') == 'http.response.body' and not session_ids:
            body_str = message.get('body', b'').decode('utf-8', errors='replace')
            m = _SID_RE.search(body_str)
            if m:
                sid = m.group(1)
                session_ids.append(sid)
                _SESSION_ROLES[sid] = role
        await orig_send(message)

    cv_token = _mcp_session_role.set(role)
    try:
        async with sse_transport.connect_sse(
            request.scope, request.receive, _capturing_send
        ) as streams:
            await mcp.run(streams[0], streams[1], mcp.create_initialization_options())
    finally:
        _mcp_session_role.reset(cv_token)
        for sid in session_ids:
            _SESSION_ROLES.pop(sid, None)


async def _messages_endpoint(scope, receive, send):
    from urllib.parse import parse_qs
    req = Request(scope, receive)
    auth_info = await _check_auth_request(req)
    if not auth_info:
        await Response('Unauthorized', status_code=401)(scope, receive, send)
        return

    # Set ContextVar from session dict so call_tool sees the correct role
    qs = parse_qs(scope.get('query_string', b'').decode())
    session_id = (qs.get('session_id') or [''])[0]
    role = _SESSION_ROLES.get(session_id, auth_info.get('role', 'viewer'))
    cv_token = _mcp_session_role.set(role)
    try:
        await sse_transport.handle_post_message(scope, receive, send)
    finally:
        _mcp_session_role.reset(cv_token)


def build_mcp_app() -> Starlette:
    return Starlette(routes=[
        Route('/sse', endpoint=_sse_endpoint),
        Mount('/messages', app=_messages_endpoint),
    ])
