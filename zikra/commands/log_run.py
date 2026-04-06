from zikra.db import record_run, new_id


async def cmd_log_run(body: dict) -> dict:
    run_id = new_id()
    await record_run(body, run_id)
    return {'id': run_id, 'status': 'logged'}
