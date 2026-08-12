#!/usr/bin/env python3
"""Fail closed until the verified SQLite import marker exists."""
import asyncio
import os


async def main() -> int:
    if os.getenv("ZIKRA_REQUIRE_IMPORT_MARKER", "1") in ("0", "false", "False"):
        return 0
    import asyncpg

    conn = await asyncpg.connect(
        host=os.getenv("DB_HOST", "postgres"),
        port=int(os.getenv("DB_PORT", "5432")),
        database=os.getenv("DB_NAME", "zikra"),
        user=os.getenv("DB_USER", "zikra"),
        password=os.getenv("DB_PASSWORD", ""),
    )
    try:
        value = await conn.fetchval(
            """SELECT value FROM deployment_state
               WHERE key = 'sqlite-import'"""
        )
    except asyncpg.UndefinedTableError:
        value = None
    finally:
        await conn.close()
    if value != "verified":
        raise SystemExit("Verified SQLite import marker is absent; refusing API startup")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
