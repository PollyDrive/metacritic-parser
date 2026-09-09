from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock

from metacritic_game_tracker.infrastructure.db.models import YoutubeQuotaUsageORM
from metacritic_game_tracker.infrastructure.youtube.quota_budget import YoutubeQuotaBudget


def _config(budget=80):
    config = MagicMock()
    config.get_int = AsyncMock(return_value=budget)
    return config


async def test_first_spend_of_the_day_creates_a_persisted_row(mock_session):
    mock_session.get = AsyncMock(return_value=None)
    budget = YoutubeQuotaBudget(mock_session, _config(budget=150))

    spent = await budget.try_spend(date(2026, 1, 1), 100)

    assert spent is True
    mock_session.add.assert_called_once()
    row = mock_session.add.call_args[0][0]
    assert isinstance(row, YoutubeQuotaUsageORM)
    assert row.units_spent == 100
    assert row.search_calls == 1


async def test_spend_is_read_from_the_persisted_row_not_reset_by_a_simulated_restart(mock_session):
    """A restart re-creates the budget object, but the DB row survives it."""
    existing = YoutubeQuotaUsageORM(usage_date=date(2026, 1, 1), search_calls=1, units_spent=100)
    mock_session.get = AsyncMock(return_value=existing)
    budget = YoutubeQuotaBudget(mock_session, _config(budget=150))

    spent = await budget.try_spend(date(2026, 1, 1), 40)

    assert spent is True
    assert existing.units_spent == 140
    assert existing.search_calls == 2
    mock_session.add.assert_not_called()


async def test_lookup_stops_cleanly_when_the_budget_is_exhausted(mock_session):
    existing = YoutubeQuotaUsageORM(usage_date=date(2026, 1, 1), search_calls=1, units_spent=80)
    mock_session.get = AsyncMock(return_value=existing)
    budget = YoutubeQuotaBudget(mock_session, _config(budget=80))

    spent = await budget.try_spend(date(2026, 1, 1), 100)

    assert spent is False
    assert existing.units_spent == 80
