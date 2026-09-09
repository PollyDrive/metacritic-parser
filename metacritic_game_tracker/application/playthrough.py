"""FindPlaythroughTakeawayUseCase — US4, optional scope (research.md §6).

Quota-budgeted YouTube search -> most-viewed candidate -> transcript -> LLM
takeaway, sanitized and recorded like every other LLM call. Absence of a
findable playthrough is a normal outcome, not an error (data-model.md).
"""
from __future__ import annotations

from datetime import UTC, datetime

from metacritic_game_tracker.infrastructure.db.models import LlmCallORM, PlaythroughTakeawayORM
from metacritic_game_tracker.infrastructure.youtube.playthrough_finder import (
    SEARCH_COST_UNITS,
    find_most_relevant_playthrough,
)
from metacritic_game_tracker.shared.guardrail import sanitize_input, truncate_to_limit
from metacritic_game_tracker.shared.llm_config import REASONING_ROUTE


def _build_prompt(transcript: str) -> str:
    return (
        "Below is a transcript of a YouTube playthrough of a video game. In 2-4 "
        "sentences, summarize the key takeaway a viewer would get from watching it, "
        "based only on this transcript. Do NOT include any Markdown headers (like # Title).\n\n" + transcript
    )


class FindPlaythroughTakeawayUseCase:
    def __init__(self, session, budget, search_videos, get_transcript, llm_call):
        self._session = session
        self._budget = budget
        self._search_videos = search_videos
        self._get_transcript = get_transcript
        self._llm_call = llm_call

    async def run(self, game) -> bool:
        today = datetime.now(UTC).date()
        if not await self._budget.try_spend(today, SEARCH_COST_UNITS):
            return False

        candidate = await find_most_relevant_playthrough(game.title, self._search_videos)
        if candidate is None:
            return False

        transcript = await self._get_transcript(candidate.video_id)
        if not transcript:
            return False
        prompt = _build_prompt(truncate_to_limit(sanitize_input(transcript)))
        text, input_tokens, output_tokens, model = await self._llm_call(REASONING_ROUTE, prompt)

        now = datetime.now(UTC)
        self._session.add(
            LlmCallORM(
                call_type="playthrough_takeaway",
                game_id=game.id,
                model=model,
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
        return True
