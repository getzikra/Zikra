from zikra.db import record_error, new_id


async def cmd_log_error(body: dict) -> dict:
    error_id = new_id()
    await record_error(body, error_id)
    return {'id': error_id, 'status': 'logged'}
