from zikra.version import __version__


async def cmd_version(_body: dict) -> dict:
    return {
        'version': __version__,
        'server':  'zikra',
    }
