"""ReviewEnrichmentUseCase — standalone orchestrator for review fetching,
summarization, and DB storage (research.md §7).

Used both by the primary ingest pipeline for new games and by the background
backfill process for missing or expired (Decayed TTL) reviews. Centralizes
MetacriticClient usage and DB operations.

Reviews are split per platform on Metacritic (a multi-platform game has an
independent review pool per platform) — a cheap stats sweep across every
platform_scores row picks whichever platform has the most reviews for this
audience, and that sweep's per-platform scores also refresh every platform's
userscore pill in the same pass (audience == "user"), decoupled from whether
a full regeneration is actually due. A regeneration (the paginated quote
pull + LLM call) only happens once the winning platform's review count has
grown by `growth_threshold` since the summary on file. If the review API's
shape breaks, or every platform's stats call fails, this falls back to the
SSR page parser (`parser.parse_reviews`, capped at whatever that page
embeds) rather than silently stalling.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from metacritic_game_tracker.domain.rules import calculate_next_refresh
from metacritic_game_tracker.infrastructure.db.models import (
    GameActivityEventORM,
    GameORM,
    LlmCallORM,
    ReviewSummaryORM,
)
from metacritic_game_tracker.infrastructure.scraper import parser
from metacritic_game_tracker.infrastructure.scraper.metacritic_client import ScrapeBlockedError
from metacritic_game_tracker.infrastructure.scraper.review_api import (
    ReviewApiShapeError,
    fetch_review_sample,
    pick_best_platform,
    platform_url_slug,
)

log = logging.getLogger(__name__)

# Gate-checked: any of these means the JSON API can't be trusted for this
# call, so the caller falls back to the SSR page parser entirely — never
# trusts a partially-parsed response.
_API_FAILURES = (ReviewApiShapeError, httpx.HTTPError, ScrapeBlockedError)


async def _zero_cost(model: str, input_tokens: int, output_tokens: int) -> Decimal:
    return Decimal("0")


class ReviewEnrichmentUseCase:
    def __init__(self, session: AsyncSession, fetch_reviews, summarize, fetch_review_json, get_cost_usd=None):
        """
        fetch_reviews: async (slug: str, audience: str) -> str (HTML) — SSR fallback
        summarize: async (quotes: list[str], audience: str) -> result
        fetch_review_json: async (url: str) -> str (JSON body) — the review API
        get_cost_usd: async (model: str, input_tokens: int, output_tokens: int) -> Decimal —
            defaults to a zero-cost stub so existing/unit-test call sites that don't care about
            billing don't need to wire one; production wiring (scripts/run_scheduler.py,
            application/ingest.py) passes the real meta.llm_model_costs-backed lookup.
        """
        self._session = session
        self._fetch_reviews = fetch_reviews
        self._summarize = summarize
        self._fetch_review_json = fetch_review_json
        self._get_cost_usd = get_cost_usd or _zero_cost

    async def run(
        self, game: GameORM, audience: str, sample_size: int, growth_threshold: int = 1,
        run_id: int | None = None, recent_tier_days: int = 3, mid_tier_days: int = 7,
        max_age_weeks: int = 4,
    ) -> None:
        """Fetch (if due), summarize, and upsert a review summary, pushing the
        TTL forward only once a replacement is actually ready. Never deletes
        the existing row up front — an empty or failed fetch must leave a
        working summary exactly as it was, not wipe it out."""
        existing = await self._session.execute(
            select(ReviewSummaryORM).where(
                ReviewSummaryORM.game_id == game.id, ReviewSummaryORM.audience == audience
            )
        )
        row = existing.scalar_one_or_none()
        previous_total = row.total_reviews_count if row is not None else 0

        slug = game.metacritic_slug
        platform_names = [ps.platform for ps in game.platform_scores] or [None]

        pick = None
        if platform_names[0] is not None:
            pick = await pick_best_platform(self._fetch_review_json, slug, audience, platform_names)

        if pick is not None and audience == "user":
            # Free byproduct of the sweep already done above — refresh every
            # platform's userscore pill, not just the one picked for
            # summarization. Real bug this fixes: reviews got summarized
            # successfully while the pills stayed "tbd" forever, because
            # nothing else in the pipeline ever wrote platform_scores.userscore.
            for ps in game.platform_scores:
                if ps.platform in pick.scores_by_platform:
                    score = pick.scores_by_platform[ps.platform]
                    if score is not None:
                        ps.userscore = score

        quotes, total_count, source_platform = await self._fetch_due(
            slug, audience, sample_size, growth_threshold, previous_total, pick
        )
        if quotes is None:
            # Below-threshold recheck: no LLM call, no summary change — but the
            # decay-curve clock still advances, or this game would stay "due"
            # and get re-fetched on every single tick forever (FR-005/SC-002).
            game.next_refresh_at = calculate_next_refresh(
                game.release_date, datetime.now(UTC), recent_tier_days, mid_tier_days, max_age_weeks
            )
            return
        if not quotes:
            raise ValueError(f"No {audience} reviews found")

        try:
            result = await self._summarize(quotes, audience)
        except Exception as exc:
            # llm_calls only ever recorded successes before — a failing call
            # left zero trace there (still visible via enrichment_attempts /
            # pipeline_rejects, but that table itself was 100%
            # survivorship-biased). model is unknown here — the concrete
            # route is an infra concern the application layer doesn't see.
            self._session.add(
                LlmCallORM(
                    call_type=f"{audience}_summary",
                    game_id=game.id,
                    model="unknown",
                    status="error",
                    error_message=str(exc),
                    created_at=datetime.now(UTC),
                )
            )
            raise

        now = datetime.now(UTC)
        cost_usd = await self._get_cost_usd(result.model, result.input_tokens, result.output_tokens)

        self._session.add(
            LlmCallORM(
                call_type=f"{audience}_summary",
                game_id=game.id,
                model=result.model,
                cost_usd=cost_usd,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                status="ok",
                created_at=now,
            )
        )

        if row is None:
            row = ReviewSummaryORM(game_id=game.id, audience=audience)
            self._session.add(row)

        source_url = (
            f"https://www.metacritic.com/game/{slug}/{audience}-reviews/"
            f"?platform={platform_url_slug(source_platform)}"
            if source_platform else f"https://www.metacritic.com/game/{slug}/{audience}-reviews/"
        )

        row.summary_text = result.summary_text
        row.generated_at = now
        row.total_reviews_count = total_count
        row.sampled_reviews_count = len(quotes)
        row.source_url = source_url
        row.source_platform = source_platform

        # first_pass is display-only history (kept via the activity-event
        # log, unlike the threshold baseline above which now lives directly
        # on the row) — scanned oldest-first so it survives however many
        # refreshes later, pinned to what the initial load actually found.
        history = await self._session.execute(
            select(GameActivityEventORM)
            .where(
                GameActivityEventORM.game_id == game.id,
                GameActivityEventORM.event_type == "review_refresh",
            )
            .order_by(GameActivityEventORM.created_at.asc())
        )
        matching = [e for e in history.scalars().all() if e.details.get("audience") == audience]
        if matching:
            oldest = matching[0].details
            first_pass = oldest.get("first_pass_total_reviews", oldest.get("total_reviews", total_count))
        else:
            first_pass = total_count  # no history: this run IS the first pass

        delta = total_count - previous_total
        delta_str = f"+{delta}" if delta > 0 else str(delta)

        self._session.add(
            GameActivityEventORM(
                game_id=game.id,
                run_id=run_id,
                event_type="review_refresh",
                created_at=now,
                details={
                    "audience": audience,
                    "platform": source_platform,
                    "total_reviews": total_count,
                    "previous_total_reviews": previous_total,
                    "delta": delta_str,
                    "sampled_reviews": len(quotes),
                    "first_pass_total_reviews": first_pass,
                }
            )
        )

        # Decayed TTL is keyed strictly on release_date, per README/domain
        # rule: a game with no resolvable release_date never gets a scheduled
        # refresh (calculate_next_refresh returns None for it) — this summary
        # still stays as-is until a future ingest run resolves a real
        # release_date. Falling back to first_seen_at here would misrepresent
        # a game as freshly-released and schedule refreshes the TTL policy
        # never intended.
        game.next_refresh_at = calculate_next_refresh(
            game.release_date, now, recent_tier_days, mid_tier_days, max_age_weeks
        )

    async def _fetch_due(
        self, slug: str, audience: str, sample_size: int, growth_threshold: int,
        previous_total: int, pick,
    ) -> tuple[list[str] | None, int, str | None]:
        """Returns (quotes, total_count, source_platform). quotes is None when
        the sweep succeeded but growth hasn't cleared the threshold —
        nothing to do. source_platform is None only on the SSR fallback
        path, where no reliable per-platform attribution exists."""
        if pick is None:
            # No platform stats signal at all (no platform_scores rows, or
            # every platform's stats call failed) — better to occasionally
            # over-regenerate on an API hiccup than silently freeze growth
            # tracking for this game until the API recovers.
            log.warning("No review-platform stats available for %s/%s — falling back to the SSR page", slug, audience)
            html = await self._fetch_reviews(slug, audience)
            quotes = parser.parse_reviews(html, sample_size)
            return quotes, max(previous_total, len(quotes)), None

        due = previous_total == 0 or (pick.best_review_count - previous_total) >= growth_threshold
        if not due:
            return None, pick.best_review_count, pick.best_platform

        try:
            quotes, total_count = await fetch_review_sample(
                self._fetch_review_json, slug, audience, platform_url_slug(pick.best_platform), cap=sample_size
            )
        except _API_FAILURES as exc:
            log.warning(
                "Review API sample pull failed for %s/%s (%s) after a successful stats sweep — "
                "falling back to the SSR page: %s", slug, audience, pick.best_platform, exc,
            )
            html = await self._fetch_reviews(slug, audience)
            quotes = parser.parse_reviews(html, sample_size)
            total_count = pick.best_review_count  # the stats sweep DID succeed — keep it, it's accurate
        return quotes, total_count, pick.best_platform
