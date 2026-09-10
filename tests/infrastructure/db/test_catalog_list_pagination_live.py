"""Regression test against a real Postgres connection, not a mocked session.

The bug: `GameRepository.list(sort="rating")` outer-joins `platform_scores`
and orders/limits directly on the joined result — a game with N platforms
contributes N rows to that joined result, so `LIMIT page_size` can cut off
after far fewer than `page_size` *distinct* games once Python-side
`.scalars().unique()` collapses the duplicates. A mocked session can't catch
this: it never actually fans out rows the way a real JOIN does (same class of
bug as test_upsert_platform_scores_live.py — real ORM/SQL behavior, not
application logic).
"""
from __future__ import annotations

import os
from datetime import UTC, datetime

from dotenv import dotenv_values
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from metacritic_game_tracker.infrastructure.db.models import GameORM, PlatformScoreORM
from metacritic_game_tracker.infrastructure.db.repositories import GameRepository

import pytest

_DATABASE_URL = os.environ.get("DATABASE_URL") or dotenv_values().get("DATABASE_URL")

_BASE_ID = 999999800  # dedicated test id range, never committed (session.rollback())


@pytest.mark.skipif(not _DATABASE_URL, reason="DATABASE_URL not set (e.g. in CI)")


async def test_list_sorted_by_rating_returns_the_full_page_even_with_multi_platform_games():
    engine = create_async_engine(_DATABASE_URL)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessionmaker() as session:
            # 5 games, each with 3 platforms, scores staggered so ordering is
            # deterministic — 15 platform_score rows behind only 5 games.
            now = datetime.now(UTC)
            for i in range(5):
                game = GameORM(
                    metacritic_id=_BASE_ID + i,
                    metacritic_slug=f"pagination-fanout-test-{i}",
                    title=f"Pagination Fanout Test {i}",
                    genres=[],
                    first_seen_at=now,
                    last_updated_at=now,
                    platform_scores=[
                        PlatformScoreORM(platform=f"Platform{i}-{p}", metascore=90 - i, updated_at=now)
                        for p in range(3)
                    ],
                )
                session.add(game)

            repo = GameRepository(session)
            games = await repo.list(sort="rating", limit=5, offset=0)

            assert len(games) == 5
            assert len({g.id for g in games}) == 5  # genuinely 5 distinct games

            await session.rollback()
    finally:
        await engine.dispose()


@pytest.mark.skipif(not _DATABASE_URL, reason="DATABASE_URL not set (e.g. in CI)")
async def test_list_sorted_by_rating_combined_with_a_platform_filter_does_not_double_join():
    """Regression: the sort=rating branch used to always add its own
    outerjoin(PlatformScoreORM) even when the platform filter above had
    already joined the same table — two joins to the same unaliased table in
    one query. Combining a platform filter with the default sort=rating
    (routes_catalog.py's default) is the common case, not an edge one."""
    engine = create_async_engine(_DATABASE_URL)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessionmaker() as session:
            now = datetime.now(UTC)
            game = GameORM(
                metacritic_id=_BASE_ID + 100,
                metacritic_slug="pagination-fanout-filter-test",
                title="Pagination Fanout Filter Test",
                genres=[],
                first_seen_at=now,
                last_updated_at=now,
                platform_scores=[
                    PlatformScoreORM(platform="PaginationFanoutTestPlatform", metascore=80, updated_at=now),
                    PlatformScoreORM(platform="PaginationFanoutTestPlatform2", metascore=90, updated_at=now),
                ],
            )
            session.add(game)

            repo = GameRepository(session)
            games = await repo.list(
                platform="PaginationFanoutTestPlatform", sort="rating", limit=5, offset=0
            )

            assert len(games) == 1
            assert games[0].metacritic_id == _BASE_ID + 100

            await session.rollback()
    finally:
        await engine.dispose()
