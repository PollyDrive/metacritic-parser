"""FindPlaythroughTakeawayUseCase — US4, optional scope (research.md §6).

Quota-budgeted YouTube search -> most-viewed candidate -> transcript -> LLM
takeaway, sanitized and recorded like every other LLM call. Absence of a
findable playthrough is a normal outcome, not an error (data-model.md).
"""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from metacritic_game_tracker.application.backfill import RunBudgetExhausted
from metacritic_game_tracker.infrastructure.db.models import (
    GameActivityEventORM,
    LlmCallORM,
    PipelineRejectORM,
    PlaythroughTakeawayORM,
)
from metacritic_game_tracker.infrastructure.youtube.playthrough_finder import (
    SEARCH_COST_UNITS,
    find_playthrough_candidates,
)
from metacritic_game_tracker.shared.guardrail import sanitize_input, truncate_to_limit
from metacritic_game_tracker.shared.llm_config import REASONING_ROUTE


def _build_prompt(transcript: str) -> str:
    return (
        "Below is a transcript of a YouTube review of a video game. In 2-4 "
        "sentences, summarize the key takeaway a viewer would get from watching it, "
        "based only on this transcript. Do NOT include any Markdown headers (like # Title).\n\n" + transcript
    )


async def _zero_cost(model: str, input_tokens: int, output_tokens: int) -> Decimal:
    return Decimal("0")


class FindPlaythroughTakeawayUseCase:
    def __init__(self, session, budget, search_videos, get_transcript, llm_call, get_cost_usd=None):
        self._session = session
        self._budget = budget
        self._search_videos = search_videos
        self._get_transcript = get_transcript
        self._llm_call = llm_call
        self._get_cost_usd = get_cost_usd or _zero_cost

    async def run(self, game, run_id: int | None = None) -> bool:
        today = datetime.now(UTC).date()
        if not await self._budget.try_spend(today, SEARCH_COST_UNITS):
            # Run-wide, not per-game — every remaining game would fail the
            # same way today, so the caller (BackfillEnrichmentUseCase) stops
            # the whole run here instead of looping through the rest.
            raise RunBudgetExhausted("Daily YouTube search quota exhausted")

        ranked_candidates = await find_playthrough_candidates(game.title, self._search_videos)
        if not ranked_candidates:
            self._session.add(
                PipelineRejectORM(
                    stage="playthrough",
                    run_id=run_id,
                    item_ref=str(game.id),
                    reason_code="no_candidate_video",
                    reason_detail=f"No YouTube search result for {game.title!r}",
                    created_at=datetime.now(UTC),
                )
            )
            return False

        # A captioned=true candidate can still have no fetchable transcript
        # (stale/wrong metadata, region lock, subtitles disabled after the
        # fact) — try every ranked candidate rather than giving up on the
        # first miss; the fetch itself spends no YouTube Data API quota.
        candidate = None
        transcript = None
        for attempt in ranked_candidates:
            transcript = await self._get_transcript(attempt.video_id)
            if transcript:
                candidate = attempt
                break

            # Cooldown to avoid tripping YouTube's anti-scraping rate limits
            # when falling back through multiple candidates.
            import asyncio
            await asyncio.sleep(2)

        if candidate is None:
            self._session.add(
                PipelineRejectORM(
                    stage="playthrough",
                    run_id=run_id,
                    item_ref=str(game.id),
                    reason_code="no_transcript",
                    reason_detail=(
                        f"No captions/transcript found among {len(ranked_candidates)} "
                        f"candidate(s), best: {ranked_candidates[0].video_id}"
                    ),
                    created_at=datetime.now(UTC),
                )
            )
            return False

        prompt = _build_prompt(truncate_to_limit(sanitize_input(transcript)))
        try:
            text, input_tokens, output_tokens, model = await self._llm_call(REASONING_ROUTE, prompt)
        except Exception as exc:
            self._session.add(
                LlmCallORM(
                    call_type="playthrough_takeaway",
                    game_id=game.id,
                    model=REASONING_ROUTE.model,
                    status="error",
                    error_message=str(exc),
                    created_at=datetime.now(UTC),
                )
            )
            raise

        now = datetime.now(UTC)
        cost_usd = await self._get_cost_usd(model, input_tokens, output_tokens)
        self._session.add(
            LlmCallORM(
                call_type="playthrough_takeaway",
                game_id=game.id,
                model=model,
                cost_usd=cost_usd,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                status="ok",
                created_at=now,
            )
        )
        self._session.add(
            PlaythroughTakeawayORM(
                game_id=game.id,
                video_url=f"https://www.youtube.com/watch?v={candidate.video_id}",
                video_view_count_at_selection=candidate.view_count,
                takeaway_text=text,
                generated_at=now,
            )
        )

        self._session.add(
            GameActivityEventORM(
                game_id=game.id,
                run_id=run_id,
                event_type="playthrough_generated",
                created_at=now,
                details={"video_url": f"https://www.youtube.com/watch?v={candidate.video_id}"}
            )
        )

        return True
