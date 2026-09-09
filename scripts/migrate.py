"""Idempotent SQL migration runner (research.md §1).

Applies sql/migrations/*.sql in filename order, tracking applied filenames in
a schema_migrations table so re-running is a no-op for already-applied files.
"""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

import asyncpg
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
log = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "sql" / "migrations"


def _asyncpg_dsn(database_url: str) -> str:
    return database_url.replace("postgresql+asyncpg://", "postgresql://", 1)


async def run_migrations(database_url: str) -> list[str]:
    conn = await asyncpg.connect(_asyncpg_dsn(database_url))
    try:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                filename    TEXT PRIMARY KEY,
                applied_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        applied = {row["filename"] for row in await conn.fetch("SELECT filename FROM schema_migrations")}

        newly_applied: list[str] = []
        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            if path.name in applied:
                continue
            sql = path.read_text()
            async with conn.transaction():
                await conn.execute(sql)
                await conn.execute(
                    "INSERT INTO schema_migrations (filename) VALUES ($1)", path.name
                )
            newly_applied.append(path.name)
            log.info("Applied migration: %s", path.name)

        if not newly_applied:
            log.info("No new migrations to apply")
        return newly_applied
    finally:
        await conn.close()


async def main() -> None:
    database_url = os.environ["DATABASE_URL"]
    await run_migrations(database_url)


if __name__ == "__main__":
    asyncio.run(main())
