"""Persisted YouTube Data API daily quota spend (research.md §6) — a worker
restart must not silently reset the counter and blow the daily quota, so it
lives in the DB, not in a process-local variable."""
from __future__ import annotations

from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from metacritic_game_tracker.infrastructure.config.runtime import RuntimeConfig
from metacritic_game_tracker.infrastructure.db.models import YoutubeQuotaUsageORM


class YoutubeQuotaBudget:
    def __init__(self, session: AsyncSession, config: RuntimeConfig):
        self._session = session
        self._config = config

    async def try_spend(self, today: date, units: int) -> bool:
        budget = await self._config.get_int("enrichment.youtube_daily_search_budget")
        row = await self._session.get(YoutubeQuotaUsageORM, today)
        if row is None:
            row = YoutubeQuotaUsageORM(usage_date=today, search_calls=0, units_spent=0)
            self._session.add(row)

        if row.units_spent + units > budget:
            return False

        row.units_spent += units
        row.search_calls += 1
        return True
