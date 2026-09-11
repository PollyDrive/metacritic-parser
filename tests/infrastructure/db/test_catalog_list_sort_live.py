"""Regression test against a real Postgres connection, not a mocked session.

The bug: `GameRepository.list()`'s default branch (routes_catalog.py's
sort="default", labeled "Newest" in the UI) ordered by `GameORM.id.desc()` —
insertion order, i.e. when the scraper first ingested the row, not the game's
actual release date. A game re-released or ingested late (backfill, retry,
late listing-page pickup) with an old `release_date` would show up at the top
of "Newest" ahead of games that actually released more recently. Ordering
needs to read `GameORM.release_date`, which a mocked session can't verify —
the bug is in what column the SQL orders by, not in application logic.
"""
from __future__ import annotations

import os
from datetime import UTC, date, datetime

import pytest
from dotenv import dotenv_values
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from metacritic_game_tracker.infrastructure.db.models import GameORM
from metacritic_game_tracker.infrastructure.db.repositories import GameRepository

_DATABASE_URL = os.environ.get("DATABASE_URL") or dotenv_values().get("DATABASE_URL")

_BASE_ID = 999999700  # dedicated test id range, never committed (session.rollback())


@pytest.mark.skipif(not _DATABASE_URL, reason="DATABASE_URL not set (e.g. in CI)")
async def test_default_sort_orders_by_release_date_not_insertion_order():
    engine = create_async_engine(_DATABASE_URL)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessionmaker() as session:
            now = datetime.now(UTC)
            # Inserted new-release-first so its id is LOWER than the
            # old-release game's — under the buggy id.desc() ordering the
            # OLD release would wrongly sort first; only reading
            # release_date gets this right.
            new_release_ingested_first = GameORM(
                metacritic_id=_BASE_ID + 1,
                metacritic_slug="sort-default-new-release",
                title="Sort Default New Release",
                genres=[],
                release_date=date(2026, 1, 1),
                first_seen_at=now,
                last_updated_at=now,
            )
            old_release_ingested_last = GameORM(
                metacritic_id=_BASE_ID,
                metacritic_slug="sort-default-old-release",
                title="Sort Default Old Release",
                genres=[],
                release_date=date(2020, 1, 1),
                first_seen_at=now,
                last_updated_at=now,
            )
            session.add(new_release_ingested_first)
            await session.flush()
            session.add(old_release_ingested_last)
            await session.flush()
            # old_release_ingested_last has the HIGHER id (inserted last)
            # despite having the OLDER release_date.
            assert old_release_ingested_last.id > new_release_ingested_first.id

            repo = GameRepository(session)
            games = await repo.list(sort="default", limit=100000, offset=0)
            titles = [g.title for g in games if g.metacritic_id in (_BASE_ID, _BASE_ID + 1)]

            assert titles == ["Sort Default New Release", "Sort Default Old Release"]

            await session.rollback()
    finally:
        await engine.dispose()
