"""Startup migrations: Alembic for Postgres; create_all for SQLite (dev/tests)."""

from pathlib import Path

import anyio
from sqlalchemy import inspect

from .config import get_settings
from .db import engine, init_db

ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"


async def run_migrations() -> None:
    settings = get_settings()
    if settings.database_url.startswith("sqlite"):
        await init_db()
        return

    # wait for the DB forever (Docker can be mid-start, the host waking from
    # sleep, or the user away for days) — never crash the API over it
    import asyncio
    import logging

    log = logging.getLogger("migrate")
    tables: set[str] = set()
    attempt = 0
    while True:
        try:
            async with engine.connect() as conn:
                tables = await conn.run_sync(lambda c: set(inspect(c).get_table_names()))
            if attempt:
                log.info("DB reachable again after %d retries", attempt)
            break
        except Exception as exc:
            attempt += 1
            # fast retry for the first minute, then settle into 10s — quiet logs
            await asyncio.sleep(3 if attempt <= 20 else 10)
            if attempt <= 20 or attempt % 30 == 0:
                log.warning("DB not reachable (%s) — retry %d", type(exc).__name__, attempt)

    # DB predates Alembic (tables exist, no version row) -> mark as current, then upgrade
    stamp_first = "users" in tables and "alembic_version" not in tables

    def _upgrade() -> None:
        from alembic import command
        from alembic.config import Config

        cfg = Config(str(ALEMBIC_INI))
        if stamp_first:
            command.stamp(cfg, "head")
        command.upgrade(cfg, "head")

    await anyio.to_thread.run_sync(_upgrade)
