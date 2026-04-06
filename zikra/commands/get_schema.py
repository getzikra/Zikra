from zikra.db import get_schema_info


async def cmd_get_schema(body: dict) -> dict:
    return await get_schema_info()
