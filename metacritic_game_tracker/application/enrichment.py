"""ReviewEnrichmentUseCase — standalone orchestrator for review fetching,
summarization, and DB storage (research.md §7).

Used both by the primary ingest pipeline for new games and by the background
backfill process for missing or expired (Decayed TTL) reviews. Centralizes
MetacriticClient usage and DB operations.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from metacritic_game_tracker.domain.rules import calculate_next_refresh
from metacritic_game_tracker.infrastructure.db.models import GameORM, LlmCallORM, ReviewSummaryORM
from metacritic_game_tracker.infrastructure.scraper import parser

log = logging.getLogger(__name__)


class ReviewEnrichmentUseCase:
    def __init__(self, session: AsyncSession, fetch_reviews, summarize):
        """
        fetch_reviews: async (slug: str, audience: str) -> str (HTML)
        summarize: async (quotes: list[str], audience: str) -> result
        """
        self._session = session
        self._fetch_reviews = fetch_reviews
        self._summarize = summarize

    async def run(self, game: GameORM, audience: str, sample_size: int) -> None:
        """Fetch, summarize, and upsert a review summary, pushing the TTL
        forward only once a replacement is actually ready. Never deletes the
        existing row up front — an empty or failed fetch must leave a working
        summary exactly as it was, not wipe it out."""
        html = await self._fetch_reviews(game.metacritic_slug, audience)
        quotes = parser.parse_reviews(html, sample_size)
        if not quotes:
            raise ValueError(f"No {audience} reviews found")

        result = await self._summarize(quotes, audience)
        now = datetime.now(UTC)

        self._session.add(
            LlmCallORM(
                call_type=f"{audience}_summary",
                game_id=game.id,
                model=result.model,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                status="ok",
                created_at=now,
            )
        )

        existing = await self._session.execute(
            select(ReviewSummaryORM).where(
                ReviewSummaryORM.game_id == game.id, ReviewSummaryORM.audience == audience
            )
        )
        row = existing.scalar_one_or_none()
        if row is None:
            row = ReviewSummaryORM(game_id=game.id, audience=audience)
            self._session.add(row)
        row.summary_text = result.summary_text
        row.generated_at = now

        # Anchor age on when we first cataloged the game when Metacritic's own
        # release_date is unresolved, so a game with no known release date
        # still gets refreshed on schedule instead of silently never again.
        anchor_date = game.release_date or game.first_seen_at.date()
        game.next_refresh_at = calculate_next_refresh(anchor_date, now)
