from zikra.db import record_error, new_id


async def cmd_log_error(body: dict) -> dict:
    message = body.get('message') or body.get('error', '')
    if not message or not message.strip():
        return {
            'error': "message is required (use field name 'message' or 'error')",
            'hint': "field name 'title' is not stored — use 'message' instead",
        }
    error_id = new_id()
    await record_error(body, error_id)
    return {'id': error_id, 'status': 'logged'}
