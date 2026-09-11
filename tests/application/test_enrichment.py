from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from metacritic_game_tracker.application.enrichment import ReviewEnrichmentUseCase
from metacritic_game_tracker.infrastructure.db.models import (
    GameActivityEventORM,
    GameORM,
    PlatformScoreORM,
    ReviewSummaryORM,
)

_TODAY = datetime.now(UTC)
_UNSET = object()


def _game(release_date=_UNSET, first_seen_at=None, platforms=("PC",)):
    game = GameORM(
        id=1, metacritic_id=1, metacritic_slug="elden-ring", title="Elden Ring",
        release_date=(_TODAY.date() if release_date is _UNSET else release_date),
        first_seen_at=first_seen_at or _TODAY,
    )
    game.platform_scores = [PlatformScoreORM(platform=p, metascore=80) for p in platforms]
    return game


def _review_json(total: int, quotes: list[str]) -> str:
    return json.dumps({"data": {"totalResults": total, "items": [{"quote": q} for q in quotes]}})


def _stats_json(review_count: int, score: float | None = None) -> str:
    return json.dumps({"data": {"item": {"reviewCount": review_count, "score": score, "max": 100}}})


def _fetch_json_for(total: int, quotes: list[str], score: float | None = None):
    """Single-platform scenario: dispatches by URL shape — the stats endpoint
    gets {reviewCount: total, score}, the list endpoint gets {totalResults:
    total, items: quotes}. Every page (any offset) returns the same `quotes`
    batch — fine for tests that only care about the first page / a small
    quote count."""
    async def fetch_json(url):
        if "/stats/web" in url:
            return _stats_json(total, score)
        return _review_json(total, quotes)
    return fetch_json


def _session_with_existing(row, prior_events=()):
    """A due run issues two SELECTs in order: the existing ReviewSummaryORM
    row, then the game's review_refresh activity events (first-pass display
    history) — mocked as two sequential session.execute() results. A NOT-due
    run only ever issues the first."""
    session = AsyncMock()
    session.add = MagicMock()

    summary_result = MagicMock()
    summary_result.scalar_one_or_none.return_value = row

    events_result = MagicMock()
    events_result.scalars.return_value.all.return_value = list(prior_events)

    session.execute.side_effect = [summary_result, events_result]
    return session


def _summary_row(total_reviews_count=0, **kw):
    return ReviewSummaryORM(
        id=5, game_id=1, audience="critic", summary_text="old",
        generated_at=datetime(2025, 1, 1, tzinfo=UTC),
        total_reviews_count=total_reviews_count, sampled_reviews_count=0, **kw,
    )


async def test_persists_a_new_summary_on_the_first_pass_regardless_of_threshold():
    session = _session_with_existing(None)
    fetch_reviews = AsyncMock()  # SSR fallback must not be needed
    summarize = AsyncMock(
        return_value=MagicMock(summary_text="Great game.", input_tokens=10, output_tokens=5, model="m")
    )
    use_case = ReviewEnrichmentUseCase(
        session, fetch_reviews, summarize, fetch_review_json=_fetch_json_for(24, ["quote"])
    )

    game = _game()
    await use_case.run(game, "critic", sample_size=50, growth_threshold=10)

    added_types = [type(c.args[0]).__name__ for c in session.add.call_args_list]
    assert "LlmCallORM" in added_types
    assert "ReviewSummaryORM" in added_types
    assert "GameActivityEventORM" in added_types
    assert game.next_refresh_at is not None
    fetch_reviews.assert_not_awaited()


async def test_persisted_summary_row_carries_the_real_total_sample_size_platform_and_source_link():
    session = _session_with_existing(None)
    summarize = AsyncMock(
        return_value=MagicMock(summary_text="Great game.", input_tokens=1, output_tokens=1, model="m")
    )
    use_case = ReviewEnrichmentUseCase(
        session, AsyncMock(), summarize,
        fetch_review_json=_fetch_json_for(93, [f"q{i}" for i in range(10)]),
    )

    await use_case.run(_game(platforms=("PC",)), "critic", sample_size=10, growth_threshold=10)

    row = next(c.args[0] for c in session.add.call_args_list if type(c.args[0]).__name__ == "ReviewSummaryORM")
    assert row.total_reviews_count == 93
    assert row.sampled_reviews_count == 10
    assert row.source_platform == "PC"
    assert row.source_url == "https://www.metacritic.com/game/elden-ring/critic-reviews/?platform=pc"


async def test_picks_the_platform_with_the_most_reviews_for_summarization():
    """Real bug this fixes: reviews are split per platform on Metacritic — a
    fixed default platform was being summarized regardless of where the
    actual review volume was."""
    session = _session_with_existing(None)
    summarize = AsyncMock(
        return_value=MagicMock(summary_text="text", input_tokens=1, output_tokens=1, model="m")
    )

    async def fetch_json(url):
        if "/stats/web" in url:
            if "/platform/playstation-5/" in url:
                return _stats_json(334, 8.6)
            if "/platform/pc/" in url:
                return _stats_json(31, 9.3)
            return _stats_json(2, 5.0)
        if "/platform/playstation-5/" in url:
            return _review_json(334, [f"ps5-q{i}" for i in range(20)])
        raise AssertionError(f"summarization should only pull from the winning platform: {url}")

    use_case = ReviewEnrichmentUseCase(session, AsyncMock(), summarize, fetch_review_json=fetch_json)
    game = _game(platforms=("PlayStation 5", "PC", "Xbox Series X"))

    await use_case.run(game, "user", sample_size=20, growth_threshold=10)

    summarize.assert_awaited_once_with([f"ps5-q{i}" for i in range(20)], "user")
    row = next(c.args[0] for c in session.add.call_args_list if type(c.args[0]).__name__ == "ReviewSummaryORM")
    assert row.source_platform == "PlayStation 5"
    assert row.total_reviews_count == 334


async def test_refreshes_every_platforms_userscore_pill_from_the_same_stats_sweep():
    """Real bug this fixes: user reviews got summarized successfully while
    every platform's userscore pill stayed "tbd" forever, because nothing in
    the pipeline ever actually wrote platform_scores.userscore. The sweep
    used to pick the winning platform already has every platform's score —
    apply all of them, not just the winner's."""
    session = _session_with_existing(None)
    summarize = AsyncMock(
        return_value=MagicMock(summary_text="text", input_tokens=1, output_tokens=1, model="m")
    )

    async def fetch_json(url):
        if "/stats/web" in url:
            if "/platform/playstation-5/" in url:
                return _stats_json(334, 8.6)
            if "/platform/pc/" in url:
                return _stats_json(31, 9.3)
            return _stats_json(0, None)
        return _review_json(334, [f"q{i}" for i in range(20)])

    use_case = ReviewEnrichmentUseCase(session, AsyncMock(), summarize, fetch_review_json=fetch_json)
    game = _game(platforms=("PlayStation 5", "PC", "Xbox Series X"))

    await use_case.run(game, "user", sample_size=20, growth_threshold=10)

    scores = {ps.platform: ps.userscore for ps in game.platform_scores}
    assert scores == {"PlayStation 5": 8.6, "PC": 9.3, "Xbox Series X": None}


async def test_does_not_touch_userscore_pills_for_the_critic_audience():
    """Userscore is a user-review concept — a critic-audience pass sweeps
    critic review stats (to pick the winning platform for the critic
    summary) and must not write anything into platform_scores.userscore."""
    session = _session_with_existing(None)
    summarize = AsyncMock(
        return_value=MagicMock(summary_text="text", input_tokens=1, output_tokens=1, model="m")
    )
    use_case = ReviewEnrichmentUseCase(
        session, AsyncMock(), summarize, fetch_review_json=_fetch_json_for(14, ["q1"], score=89)
    )
    game = _game(platforms=("PC",))

    await use_case.run(game, "critic", sample_size=50, growth_threshold=10)

    assert game.platform_scores[0].userscore is None


async def test_a_recheck_below_the_growth_threshold_makes_no_llm_call_and_changes_nothing():
    """Core mechanic: a recheck whose total hasn't grown by at least
    `growth_threshold` since the summary on file does nothing — no
    summarize() call, no ReviewSummaryORM/event writes, the cheap stats
    sweep is the only cost."""
    existing = _summary_row(total_reviews_count=90)
    session = _session_with_existing(existing)
    summarize = AsyncMock()
    fetch_review_json = AsyncMock(return_value=_stats_json(95))
    use_case = ReviewEnrichmentUseCase(session, AsyncMock(), summarize, fetch_review_json=fetch_review_json)

    result = await use_case.run(_game(), "critic", sample_size=50, growth_threshold=10)

    assert result is None
    summarize.assert_not_awaited()
    session.add.assert_not_called()
    assert session.execute.await_count == 1  # only the summary lookup — no event-history scan
    fetch_review_json.assert_awaited_once()  # exactly one request: the one platform's stats probe


async def test_a_recheck_below_threshold_still_advances_next_refresh_at():
    """FR-005/FR-007/SC-002: a recheck that doesn't clear the threshold must
    still push the decay-curve clock forward — otherwise the game stays
    'due' and gets re-fetched every single tick forever instead of waiting
    out its configured interval."""
    existing = _summary_row(total_reviews_count=90)
    session = _session_with_existing(existing)
    summarize = AsyncMock()
    fetch_review_json = AsyncMock(return_value=_stats_json(95))  # +5, under threshold 10
    use_case = ReviewEnrichmentUseCase(session, AsyncMock(), summarize, fetch_review_json=fetch_review_json)

    game = _game()
    await use_case.run(game, "critic", sample_size=50, growth_threshold=10)

    summarize.assert_not_awaited()
    assert game.next_refresh_at is not None


async def test_a_lower_observed_count_than_recorded_is_not_growth():
    """Edge case: Metacritic removed reviews (spam cleanup) — a drop must
    never be treated as growth, and must not touch the existing summary or
    its recorded count."""
    existing = _summary_row(total_reviews_count=90)
    session = _session_with_existing(existing)
    summarize = AsyncMock()
    fetch_review_json = AsyncMock(return_value=_stats_json(80))  # dropped from 90 to 80
    use_case = ReviewEnrichmentUseCase(session, AsyncMock(), summarize, fetch_review_json=fetch_review_json)

    result = await use_case.run(_game(), "critic", sample_size=50, growth_threshold=10)

    assert result is None
    summarize.assert_not_awaited()
    assert existing.summary_text == "old"
    assert existing.total_reviews_count == 90


async def test_a_recheck_at_or_above_the_growth_threshold_regenerates():
    existing = _summary_row(total_reviews_count=90)
    session = _session_with_existing(existing)
    summarize = AsyncMock(
        return_value=MagicMock(summary_text="Updated.", input_tokens=1, output_tokens=1, model="m")
    )
    use_case = ReviewEnrichmentUseCase(
        session, AsyncMock(), summarize,
        fetch_review_json=_fetch_json_for(101, [f"q{i}" for i in range(10)]),  # +11, >= threshold 10
    )

    await use_case.run(_game(), "critic", sample_size=50, growth_threshold=10)

    summarize.assert_awaited_once()
    assert existing.summary_text == "Updated."
    assert existing.total_reviews_count == 101


async def test_records_a_review_refresh_activity_event_with_the_new_total_based_delta():
    session = _session_with_existing(None)
    summarize = AsyncMock(
        return_value=MagicMock(summary_text="Great game.", input_tokens=10, output_tokens=5, model="m")
    )
    use_case = ReviewEnrichmentUseCase(
        session, AsyncMock(), summarize, fetch_review_json=_fetch_json_for(2, ["q1", "q2"])
    )

    await use_case.run(_game(), "critic", sample_size=50, growth_threshold=1, run_id=7)

    events = [c.args[0] for c in session.add.call_args_list if type(c.args[0]).__name__ == "GameActivityEventORM"]
    assert len(events) == 1
    event = events[0]
    assert event.event_type == "review_refresh"
    assert event.run_id == 7
    assert event.game_id == 1
    assert event.details == {
        "audience": "critic", "platform": "PC", "total_reviews": 2, "previous_total_reviews": 0,
        "delta": "+2", "sampled_reviews": 2, "first_pass_total_reviews": 2,
    }


async def test_first_pass_total_is_carried_forward_from_the_oldest_matching_event():
    first_pass_event = GameActivityEventORM(
        game_id=1, event_type="review_refresh",
        created_at=datetime(2025, 1, 1, tzinfo=UTC),
        details={"audience": "critic", "total_reviews": 8, "first_pass_total_reviews": 8},
    )
    later_event = GameActivityEventORM(
        game_id=1, event_type="review_refresh",
        created_at=datetime(2025, 6, 1, tzinfo=UTC),
        details={"audience": "critic", "total_reviews": 90, "first_pass_total_reviews": 8},
    )
    existing = _summary_row(total_reviews_count=90)
    session = _session_with_existing(existing, prior_events=[first_pass_event, later_event])
    summarize = AsyncMock(
        return_value=MagicMock(summary_text="text", input_tokens=1, output_tokens=1, model="m")
    )
    use_case = ReviewEnrichmentUseCase(
        session, AsyncMock(), summarize,
        fetch_review_json=_fetch_json_for(101, [f"q{i}" for i in range(15)]),
    )

    await use_case.run(_game(), "critic", sample_size=50, growth_threshold=10)

    events = [c.args[0] for c in session.add.call_args_list if type(c.args[0]).__name__ == "GameActivityEventORM"]
    assert events[0].details["first_pass_total_reviews"] == 8
    assert events[0].details["previous_total_reviews"] == 90
    assert events[0].details["delta"] == "+11"


async def test_falls_back_to_the_ssr_page_when_every_platforms_stats_call_fails():
    """Gate-checked: the undocumented API can change shape without notice —
    the stats sweep failing entirely must not stop review-refresh, it must
    degrade to the SSR page parser for this pass."""
    session = _session_with_existing(None)
    fetch_reviews = AsyncMock(return_value="<html>reviews</html>")
    summarize = AsyncMock(
        return_value=MagicMock(summary_text="text", input_tokens=1, output_tokens=1, model="m")
    )

    async def broken_fetch_json(url):
        return "not json"

    use_case = ReviewEnrichmentUseCase(session, fetch_reviews, summarize, fetch_review_json=broken_fetch_json)

    import metacritic_game_tracker.application.enrichment as enrichment_module
    original = enrichment_module.parser.parse_reviews
    enrichment_module.parser.parse_reviews = lambda html, n: ["ssr quote 1", "ssr quote 2"]
    try:
        await use_case.run(_game(), "critic", sample_size=50, growth_threshold=10)
    finally:
        enrichment_module.parser.parse_reviews = original

    fetch_reviews.assert_awaited_once_with("elden-ring", "critic")
    summarize.assert_awaited_once()
    row = next(c.args[0] for c in session.add.call_args_list if type(c.args[0]).__name__ == "ReviewSummaryORM")
    assert row.sampled_reviews_count == 2
    assert row.total_reviews_count == 2  # no reliable total from a broken API — falls back to sample size
    assert row.source_platform is None  # no reliable per-platform attribution on the SSR fallback


async def test_falls_back_to_the_ssr_page_when_the_sample_pull_fails_after_a_successful_stats_sweep():
    """The stats sweep can succeed (small, cheap, likely stable) while the
    heavier paginated pull fails mid-way (network blip) — the accurate total
    from the sweep must still be kept even though the quotes come from SSR."""
    session = _session_with_existing(None)
    fetch_reviews = AsyncMock(return_value="<html>reviews</html>")
    summarize = AsyncMock(
        return_value=MagicMock(summary_text="text", input_tokens=1, output_tokens=1, model="m")
    )

    async def flaky_fetch_json(url):
        if "/stats/web" in url:
            return _stats_json(93)
        raise httpx.HTTPError("boom")  # the sample pull fails

    use_case = ReviewEnrichmentUseCase(session, fetch_reviews, summarize, fetch_review_json=flaky_fetch_json)

    import metacritic_game_tracker.application.enrichment as enrichment_module
    original = enrichment_module.parser.parse_reviews
    enrichment_module.parser.parse_reviews = lambda html, n: ["ssr quote"]
    try:
        await use_case.run(_game(), "critic", sample_size=50, growth_threshold=10)
    finally:
        enrichment_module.parser.parse_reviews = original

    row = next(c.args[0] for c in session.add.call_args_list if type(c.args[0]).__name__ == "ReviewSummaryORM")
    assert row.total_reviews_count == 93  # kept from the successful stats sweep
    assert row.sampled_reviews_count == 1  # quotes came from the SSR fallback


async def test_updates_an_existing_summary_in_place_without_deleting_it_first():
    """Regression: the previous implementation deleted the row before fetching
    reviews, so a failed/empty fetch permanently lost a working summary. It
    must upsert — mutate in place, never delete-then-maybe-reinsert."""
    existing = _summary_row()
    session = _session_with_existing(existing)
    summarize = AsyncMock(
        return_value=MagicMock(summary_text="Updated summary.", input_tokens=10, output_tokens=5, model="m")
    )
    use_case = ReviewEnrichmentUseCase(
        session, AsyncMock(), summarize, fetch_review_json=_fetch_json_for(1, ["quote"])
    )

    await use_case.run(_game(), "critic", sample_size=50, growth_threshold=1)

    assert existing.summary_text == "Updated summary."
    added_types = [type(c.args[0]).__name__ for c in session.add.call_args_list]
    assert "ReviewSummaryORM" not in added_types  # mutated existing row, not a new one


async def test_returns_false_without_retrying_when_the_stats_api_confirms_zero_reviews():
    """Real bug: a game the stats API itself reports has 0 reviews for this
    audience (pick.best_review_count == 0) used to raise, and
    BackfillEnrichmentUseCase.process_game_step retried it with exponential
    backoff for up to backfill.max_attempts runs (hours) before finally
    abandoning it — wasted effort against a condition confirmed permanent by
    the same API call that triggered the attempt. Must behave like
    playthrough's "no candidate video": produced=False, abandoned on this
    very first attempt, no backoff cycle."""
    existing = _summary_row()
    session = _session_with_existing(existing)
    summarize = AsyncMock()
    use_case = ReviewEnrichmentUseCase(
        session, AsyncMock(), summarize, fetch_review_json=_fetch_json_for(0, [])
    )

    game = _game()
    produced = await use_case.run(game, "critic", sample_size=50, growth_threshold=1)

    assert produced is False
    assert existing.summary_text == "old"
    summarize.assert_not_awaited()
    session.add.assert_not_called()


async def test_raises_when_quotes_come_back_empty_despite_a_nonzero_review_count():
    """Distinct from the permanent-zero case above: the stats sweep says
    reviews exist (best_review_count > 0), but the sample pull itself came
    back empty — a real extraction failure, not a confirmed-empty audience.
    This must still raise so BackfillEnrichmentUseCase retries it with
    backoff instead of silently giving up on a possibly-transient bug."""
    existing = _summary_row()
    session = _session_with_existing(existing)
    summarize = AsyncMock()

    async def fetch_json(url):
        if "/stats/web" in url:
            return _stats_json(5)
        return _review_json(5, [])  # stats says 5 reviews, sample pull returns none

    use_case = ReviewEnrichmentUseCase(
        session, AsyncMock(), summarize, fetch_review_json=fetch_json
    )

    game = _game()
    with pytest.raises(ValueError):
        await use_case.run(game, "critic", sample_size=50, growth_threshold=1)

    assert existing.summary_text == "old"
    summarize.assert_not_awaited()
    session.add.assert_not_called()


async def test_records_a_failed_llm_call_when_summarization_raises():
    """Real gap: llm_calls only ever recorded successes — the LlmCallORM add
    happened after a successful summarize(), so a failing LLM call left ZERO
    trace there (still visible via enrichment_attempts/pipeline_rejects, but
    llm_calls itself was 100% survivorship-biased). Log status='error' before
    re-raising, so the retry/backoff path in BackfillEnrichmentUseCase still
    works unchanged."""
    session = _session_with_existing(None)
    summarize = AsyncMock(side_effect=RuntimeError("LLM timeout"))
    use_case = ReviewEnrichmentUseCase(
        session, AsyncMock(), summarize, fetch_review_json=_fetch_json_for(1, ["quote"])
    )

    with pytest.raises(RuntimeError):
        await use_case.run(_game(), "critic", sample_size=50, growth_threshold=1)

    added = [c.args[0] for c in session.add.call_args_list if type(c.args[0]).__name__ == "LlmCallORM"]
    assert len(added) == 1
    assert added[0].status == "error"
    assert added[0].call_type == "critic_summary"
    assert "LLM timeout" in added[0].error_message
    assert session.execute.await_count == 1  # the row lookup, but never reached the summary upsert


async def test_records_cost_usd_on_the_successful_llm_call_via_the_injected_lookup():
    session = _session_with_existing(None)
    summarize = AsyncMock(
        return_value=MagicMock(summary_text="text", input_tokens=10, output_tokens=5, model="claude-haiku-4-5")
    )
    get_cost_usd = AsyncMock(return_value=Decimal("0.000042"))
    use_case = ReviewEnrichmentUseCase(
        session, AsyncMock(), summarize, fetch_review_json=_fetch_json_for(1, ["quote"]),
        get_cost_usd=get_cost_usd,
    )

    await use_case.run(_game(), "critic", sample_size=50, growth_threshold=1)

    call = next(c.args[0] for c in session.add.call_args_list if type(c.args[0]).__name__ == "LlmCallORM")
    assert call.cost_usd == Decimal("0.000042")
    get_cost_usd.assert_awaited_once_with("claude-haiku-4-5", 10, 5)


async def test_never_schedules_a_refresh_when_release_date_is_unresolved():
    """README/domain rule: Decayed TTL is keyed on release_date; a game whose
    release_date Metacritic hasn't resolved never gets a scheduled refresh
    (same as a game older than 28 days) — it is NOT treated as freshly
    released just because it was recently added to our catalog."""
    session = _session_with_existing(None)
    summarize = AsyncMock(
        return_value=MagicMock(summary_text="text", input_tokens=1, output_tokens=1, model="m")
    )
    use_case = ReviewEnrichmentUseCase(
        session, AsyncMock(), summarize, fetch_review_json=_fetch_json_for(1, ["quote"])
    )

    game = _game(release_date=None, first_seen_at=_TODAY)
    await use_case.run(game, "critic", sample_size=50, growth_threshold=1)

    assert game.next_refresh_at is None
