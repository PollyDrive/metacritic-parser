from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

from metacritic_game_tracker.application.backfill import RunBudgetExhausted
from metacritic_game_tracker.application.playthrough import FindPlaythroughTakeawayUseCase
from metacritic_game_tracker.infrastructure.db.models import GameORM, PipelineRejectORM
from metacritic_game_tracker.infrastructure.youtube.playthrough_finder import VideoCandidate


def _reject_rows(mock_session):
    return [c.args[0] for c in mock_session.add.call_args_list if isinstance(c.args[0], PipelineRejectORM)]


def _game():
    return GameORM(id=1, metacritic_id=1, metacritic_slug="elden-ring", title="Elden Ring")


def _budget(spendable=True):
    budget = MagicMock()
    budget.try_spend = AsyncMock(return_value=spendable)
    return budget


async def test_records_a_pipeline_reject_when_no_video_is_found(mock_session):
    """Real bug: this used to return False with zero trace anywhere — the
    Errors Log stayed empty even on a run where every single game failed
    here, making a 0-accepted run look causeless."""
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
    rejects = _reject_rows(mock_session)
    assert len(rejects) == 1
    assert rejects[0].reason_code == "no_candidate_video"
    assert rejects[0].item_ref == "1"


async def test_raises_run_budget_exhausted_when_the_daily_budget_is_exhausted(mock_session):
    """A run-wide condition, not a per-game one — every remaining game would
    fail identically, so this must stop the whole run (via BackfillEnrichmentUseCase
    catching RunBudgetExhausted) instead of looping through every game only to
    silently fail the same way each time."""
    search_videos = AsyncMock()

    use_case = FindPlaythroughTakeawayUseCase(
        session=mock_session,
        budget=_budget(spendable=False),
        search_videos=search_videos,
        get_transcript=AsyncMock(),
        llm_call=AsyncMock(),
    )

    try:
        await use_case.run(_game())
        raise AssertionError("expected RunBudgetExhausted")
    except RunBudgetExhausted:
        pass

    search_videos.assert_not_awaited()


async def test_records_a_pipeline_reject_when_no_captions_are_found(mock_session):
    """yt-dlp fails to find a caption track for the chosen video — a normal,
    expected outcome (not an exception), but still worth a reason in the
    Errors Log rather than silent nothing."""
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
    rejects = _reject_rows(mock_session)
    assert len(rejects) == 1
    assert rejects[0].reason_code == "no_transcript"
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
    assert mock_session.add.call_count == 3
    added_types = {type(c.args[0]).__name__ for c in mock_session.add.call_args_list}
    assert added_types == {"LlmCallORM", "PlaythroughTakeawayORM", "GameActivityEventORM"}


async def test_records_a_failed_llm_call_when_the_takeaway_call_raises(mock_session):
    """Same gap as review summarization: a failing LLM call left zero trace
    in llm_calls (only successes were ever logged). model is known
    statically here (REASONING_ROUTE), unlike enrichment.py's injected
    black-box summarize()."""
    candidate = VideoCandidate(
        video_id="abc123", title="Elden Ring Playthrough", view_count=99999, has_captions=True
    )

    async def search_videos(query: str):
        return [candidate]

    get_transcript = AsyncMock(return_value="raw transcript text")
    llm_call = AsyncMock(side_effect=RuntimeError("LLM timeout"))

    use_case = FindPlaythroughTakeawayUseCase(
        session=mock_session,
        budget=_budget(),
        search_videos=search_videos,
        get_transcript=get_transcript,
        llm_call=llm_call,
    )

    try:
        await use_case.run(_game())
        raise AssertionError("expected a RuntimeError")
    except RuntimeError:
        pass

    added = [c.args[0] for c in mock_session.add.call_args_list if type(c.args[0]).__name__ == "LlmCallORM"]
    assert len(added) == 1
    assert added[0].status == "error"
    assert added[0].model == "claude-haiku-4-5"  # REASONING_ROUTE.model
    assert "LLM timeout" in added[0].error_message


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


async def test_records_cost_usd_on_the_successful_llm_call_via_the_injected_lookup(mock_session):
    candidate = VideoCandidate(
        video_id="abc123", title="Elden Ring Playthrough", view_count=99999, has_captions=True
    )

    async def search_videos(query: str):
        return [candidate]

    get_transcript = AsyncMock(return_value="transcript text")
    llm_call = AsyncMock(return_value=("Takeaway.", 500, 100, "claude-haiku-4-5"))
    get_cost_usd = AsyncMock(return_value=Decimal("0.00091"))

    use_case = FindPlaythroughTakeawayUseCase(
        session=mock_session,
        budget=_budget(),
        search_videos=search_videos,
        get_transcript=get_transcript,
        llm_call=llm_call,
        get_cost_usd=get_cost_usd,
    )

    await use_case.run(_game())

    call = next(c.args[0] for c in mock_session.add.call_args_list if type(c.args[0]).__name__ == "LlmCallORM")
    assert call.cost_usd == Decimal("0.00091")
    get_cost_usd.assert_awaited_once_with("claude-haiku-4-5", 500, 100)
