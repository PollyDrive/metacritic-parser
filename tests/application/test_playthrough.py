from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from metacritic_game_tracker.application.playthrough import FindPlaythroughTakeawayUseCase
from metacritic_game_tracker.infrastructure.db.models import GameORM
from metacritic_game_tracker.infrastructure.youtube.playthrough_finder import VideoCandidate


def _game():
    return GameORM(id=1, metacritic_id=1, metacritic_slug="elden-ring", title="Elden Ring")


def _budget(spendable=True):
    budget = MagicMock()
    budget.try_spend = AsyncMock(return_value=spendable)
    return budget


async def test_leaves_the_game_without_a_takeaway_and_raises_nothing_when_no_video_is_found(
    mock_session,
):
    async def search_videos(query: str):
        return []

    use_case = FindPlaythroughTakeawayUseCase(
        session=mock_session,
        budget=_budget(),
        search_videos=search_videos,
        get_transcript=AsyncMock(),
        llm_call=AsyncMock(),
    )

    created = await use_case.run(_game())

    assert created is False
    mock_session.add.assert_not_called()


async def test_skips_the_search_entirely_when_the_daily_budget_is_exhausted(mock_session):
    search_videos = AsyncMock()

    use_case = FindPlaythroughTakeawayUseCase(
        session=mock_session,
        budget=_budget(spendable=False),
        search_videos=search_videos,
        get_transcript=AsyncMock(),
        llm_call=AsyncMock(),
    )

    created = await use_case.run(_game())

    assert created is False
    search_videos.assert_not_awaited()


async def test_leaves_the_game_without_a_takeaway_when_no_captions_are_found(mock_session):
    """yt-dlp fails to find a caption track for the chosen video — also a
    normal outcome, not an error (mirrors the no-video-found case)."""
    candidate = VideoCandidate(
        video_id="abc123", title="Elden Ring Playthrough", view_count=99999, has_captions=False
    )

    async def search_videos(query: str):
        return [candidate]

    llm_call = AsyncMock()

    use_case = FindPlaythroughTakeawayUseCase(
        session=mock_session,
        budget=_budget(),
        search_videos=search_videos,
        get_transcript=AsyncMock(return_value=None),
        llm_call=llm_call,
    )

    created = await use_case.run(_game())

    assert created is False
    mock_session.add.assert_not_called()
    llm_call.assert_not_awaited()


async def test_persists_a_takeaway_and_an_llm_call_when_a_video_is_found(mock_session):
    candidate = VideoCandidate(
        video_id="abc123", title="Elden Ring Playthrough", view_count=99999, has_captions=True
    )

    async def search_videos(query: str):
        return [candidate]

    get_transcript = AsyncMock(return_value="raw transcript text")
    llm_call = AsyncMock(
        return_value=("Great open world, tough bosses.", 500, 100, "claude-haiku-4-5")
    )

    use_case = FindPlaythroughTakeawayUseCase(
        session=mock_session,
        budget=_budget(),
        search_videos=search_videos,
        get_transcript=get_transcript,
        llm_call=llm_call,
    )

    created = await use_case.run(_game())

    assert created is True
    assert mock_session.add.call_count == 2
    added_types = {type(c.args[0]).__name__ for c in mock_session.add.call_args_list}
    assert added_types == {"LlmCallORM", "PlaythroughTakeawayORM"}


async def test_truncates_an_oversized_transcript_before_sending_it_to_the_llm(mock_session):
    """A multi-hour playthrough's raw transcript has no natural size cap —
    unlike review quotes (guardrail.truncate_to_limit per-quote), the prompt
    built here embeds the whole transcript. Regression: an unbounded prompt
    risks blowing past a model's context window and unpredictable cost."""
    candidate = VideoCandidate(
        video_id="abc123", title="Elden Ring Playthrough", view_count=99999, has_captions=True
    )
    oversized_transcript = "word " * 10000  # 50000 chars, well above the 20000-char guardrail limit

    async def search_videos(query: str):
        return [candidate]

    get_transcript = AsyncMock(return_value=oversized_transcript)
    llm_call = AsyncMock(return_value=("Takeaway.", 500, 100, "claude-haiku-4-5"))

    use_case = FindPlaythroughTakeawayUseCase(
        session=mock_session,
        budget=_budget(),
        search_videos=search_videos,
        get_transcript=get_transcript,
        llm_call=llm_call,
    )

    await use_case.run(_game())

    sent_prompt = llm_call.await_args.args[1]
    assert len(sent_prompt) < len(oversized_transcript)
