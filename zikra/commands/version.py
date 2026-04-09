from zikra.version import __version__


async def cmd_version(_body: dict) -> dict:
    from zikra.server import _get_latest_github_version
    latest = await _get_latest_github_version()
    result = {
        'version': __version__,
        'server':  'zikra',
    }
    if latest:
        result['latest_version'] = latest
    return result
