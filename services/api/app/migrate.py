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

    # wait for the DB (Docker can be mid-start or the host waking from sleep) —
    # never crash the whole API just because Postgres isn't reachable yet
    import asyncio
    import logging

    log = logging.getLogger("migrate")
    tables: set[str] = set()
    for attempt in range(60):  # up to ~3 minutes
        try:
            async with engine.connect() as conn:
                tables = await conn.run_sync(lambda c: set(inspect(c).get_table_names()))
            break
        except Exception as exc:
            if attempt == 59:
                raise
            log.warning("DB not reachable (%s) — retrying in 3s (%d/60)", type(exc).__name__, attempt + 1)
            await asyncio.sleep(3)

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
