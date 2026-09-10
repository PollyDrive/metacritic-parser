from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

from metacritic_game_tracker.infrastructure.db.models import LlmModelCostORM
from metacritic_game_tracker.infrastructure.llm.cost import get_cost_usd


def _session_returning(row):
    session = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = row
    session.execute.return_value = result
    return session


async def test_computes_cost_from_the_matching_rate_row():
    row = LlmModelCostORM(
        model="anthropic/claude-haiku-4-5", provider="openrouter",
        input_cost_per_1m=Decimal("0.80"), output_cost_per_1m=Decimal("4.00"),
        valid_from=date(2026, 1, 1), valid_until=None,
    )
    session = _session_returning(row)

    cost = await get_cost_usd(session, "claude-haiku-4-5", input_tokens=1_000_000, output_tokens=1_000_000)

    assert cost == Decimal("4.80")


async def test_returns_zero_when_no_rate_row_matches():
    session = _session_returning(None)

    cost = await get_cost_usd(session, "some-unknown-model", input_tokens=100, output_tokens=50)

    assert cost == Decimal("0")
