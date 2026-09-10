"""Look up meta.llm_model_costs and compute cost_usd for one LLM call.

The production LLM client (llm_client.py) returns a bare model id
(`route.model`, e.g. "claude-haiku-4-5"), while the seeded cost table keys
models with a provider prefix ("anthropic/claude-haiku-4-5") — matches
either form.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from metacritic_game_tracker.domain.rules import calculate_llm_cost
from metacritic_game_tracker.infrastructure.db.models import LlmModelCostORM

log = logging.getLogger(__name__)


async def get_cost_usd(
    session: AsyncSession, model: str, input_tokens: int, output_tokens: int
) -> Decimal:
    today = datetime.now(UTC).date()
    stmt = (
        select(LlmModelCostORM)
        .where(
            or_(LlmModelCostORM.model == model, LlmModelCostORM.model.like(f"%/{model}")),
            LlmModelCostORM.valid_from <= today,
            or_(LlmModelCostORM.valid_until.is_(None), LlmModelCostORM.valid_until >= today),
        )
        .order_by(LlmModelCostORM.valid_from.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        log.warning("No cost rate found for model %r — recording cost_usd=0", model)
        return Decimal("0")
    return calculate_llm_cost(input_tokens, output_tokens, row.input_cost_per_1m, row.output_cost_per_1m)
