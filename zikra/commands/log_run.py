from zikra.db import record_run, new_id, consume_pending_run


async def cmd_log_run(body: dict) -> dict:
    # v1.0.6 server-side handshake: if the caller didn't supply an explicit
    # prompt_id, consume the pending entry for (runner, project) from get_prompt.
    # Explicit prompt_id always wins for backwards compatibility.
    if not body.get('prompt_id'):
        runner = body.get('runner')
        project = body.get('project', 'global')
        if runner:
            pending = await consume_pending_run(runner, project)
            if pending:
                body = {**body, 'prompt_id': pending}

    run_id = new_id()
    resolved_id = await record_run(body, run_id)
    result = {'id': resolved_id, 'status': 'logged'}
    if resolved_id != run_id:
        result['deduped'] = True  # merged into the existing row for this session
    return result
