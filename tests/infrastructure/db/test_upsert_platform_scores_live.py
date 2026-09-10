"""Regression test against a real Postgres connection, not a mocked session.

The bug this catches (`sqlalchemy.exc.MissingGreenlet`) depends on SQLAlchemy's
real autoflush/loader-state machinery — a manually constructed `GameORM` that
has never been loaded via a SELECT gets silently autoflushed to a persistent
row by `upsert_platform_scores`'s own `select(PlatformScoreORM)` query, and
appending to its still-never-loaded `platform_scores` (`lazy="selectin"`)
relationship right after that triggers a genuine lazy load — which is not
awaitable from a synchronous `.append()` call. A mocked `AsyncSession` can't
reproduce this (plan.md: "repository tests against a real test DB ... or
transactional fixture" for `infrastructure/db/`).

Runs against `DATABASE_URL` (the local dev Postgres, per CLAUDE.md's
Разработка row) inside a transaction that is always rolled back — never
commits test data.
"""
from __future__ import annotations

import os

from dotenv import dotenv_values
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from metacritic_game_tracker.domain.models import PlatformScore
from metacritic_game_tracker.infrastructure.db.repositories import GameRepository
from metacritic_game_tracker.infrastructure.scraper.parser import ParsedGame

# dotenv_values(), not load_dotenv() — reads .env into a local dict instead of
# mutating the process environment, so this file doesn't leak DATABASE_URL/
# OPENCODE_API_KEY/etc. into other test modules' os.environ.setdefault() calls.
_DATABASE_URL = os.environ.get("DATABASE_URL") or dotenv_values().get("DATABASE_URL")


def _parsed() -> ParsedGame:
    return ParsedGame(
        metacritic_id=999999901,
        metacritic_slug="upsert-platform-scores-live-test",
        title="Regression Test Game",
        release_date=None,
        description="d",
        developer="Dev",
        cover_image_url=None,
        video_url=None,
        genres=[],
        platforms=[PlatformScore(platform="PC", metascore=80, userscore=8.0)],
    )


async def test_upsert_platform_scores_does_not_crash_for_a_brand_new_game():
    engine = create_async_engine(_DATABASE_URL)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessionmaker() as session:
            repo = GameRepository(session)
            parsed = _parsed()

            game, is_new = await repo.upsert(parsed)
            await repo.upsert_platform_scores(game, parsed)  # must not raise MissingGreenlet

            assert is_new is True
            assert len(game.platform_scores) == 1
            assert game.platform_scores[0].platform == "PC"

            await session.rollback()  # never persist test data
    finally:
        await engine.dispose()
