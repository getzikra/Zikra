"""run_consolidation — manually trigger the diary-consolidation job.

Optional: project (default: all projects), dry_run (report clusters without
calling the LLM or archiving anything).
"""

from zikra.consolidate import run_consolidation


async def cmd_run_consolidation(body: dict) -> dict:
    project = body.get('project') or None
    if project == 'global':
        project = None  # global means every project here
    dry_run = bool(body.get('dry_run'))
    return await run_consolidation(project=project, dry_run=dry_run)
