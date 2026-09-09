from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from metacritic_game_tracker.application.enrichment import ReviewEnrichmentUseCase
from metacritic_game_tracker.infrastructure.db.models import GameORM, ReviewSummaryORM

_TODAY = datetime.now(UTC)
_UNSET = object()


def _game(release_date=_UNSET, first_seen_at=None):
    return GameORM(
        id=1, metacritic_id=1, metacritic_slug="elden-ring", title="Elden Ring",
        release_date=(_TODAY.date() if release_date is _UNSET else release_date),
        first_seen_at=first_seen_at or _TODAY,
    )


def _session_with_existing(row):
    session = AsyncMock()
    session.add = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = row
    session.execute.return_value = result
    return session


def _stub_parse_reviews(monkeypatch, quotes):
    monkeypatch.setattr(
        "metacritic_game_tracker.application.enrichment.parser.parse_reviews",
        lambda html, n: quotes,
    )


async def test_persists_a_new_summary_and_llm_call_when_none_exists(monkeypatch):
    session = _session_with_existing(None)
    fetch_reviews = AsyncMock(return_value="<html>reviews</html>")
    summarize = AsyncMock(
        return_value=MagicMock(summary_text="Great game.", input_tokens=10, output_tokens=5, model="m")
    )
    use_case = ReviewEnrichmentUseCase(session, fetch_reviews, summarize)
    _stub_parse_reviews(monkeypatch, ["quote"])

    game = _game()
    await use_case.run(game, "critic", sample_size=20)

    added_types = [type(c.args[0]).__name__ for c in session.add.call_args_list]
    assert "LlmCallORM" in added_types
    assert "ReviewSummaryORM" in added_types
    assert game.next_refresh_at is not None


async def test_updates_an_existing_summary_in_place_without_deleting_it_first(monkeypatch):
    """Regression: the previous implementation deleted the row before fetching
    reviews, so a failed/empty fetch permanently lost a working summary. It
    must upsert — mutate in place, never delete-then-maybe-reinsert."""
    existing = ReviewSummaryORM(
        id=5, game_id=1, audience="critic", summary_text="old",
        generated_at=datetime(2025, 1, 1, tzinfo=UTC),
    )
    session = _session_with_existing(existing)
    fetch_reviews = AsyncMock(return_value="<html>reviews</html>")
    summarize = AsyncMock(
        return_value=MagicMock(summary_text="Updated summary.", input_tokens=10, output_tokens=5, model="m")
    )
    use_case = ReviewEnrichmentUseCase(session, fetch_reviews, summarize)
    _stub_parse_reviews(monkeypatch, ["quote"])

    await use_case.run(_game(), "critic", sample_size=20)

    assert existing.summary_text == "Updated summary."
    added_types = [type(c.args[0]).__name__ for c in session.add.call_args_list]
    assert "ReviewSummaryORM" not in added_types  # mutated existing row, not a new one


async def test_leaves_an_existing_summary_untouched_when_no_reviews_are_found(monkeypatch):
    """The exact bug this fixes: an empty fetch must never wipe a working summary."""
    existing = ReviewSummaryORM(
        id=5, game_id=1, audience="critic", summary_text="still good",
        generated_at=datetime(2025, 1, 1, tzinfo=UTC),
    )
    session = _session_with_existing(existing)
    fetch_reviews = AsyncMock(return_value="<html>no reviews</html>")
    summarize = AsyncMock()
    use_case = ReviewEnrichmentUseCase(session, fetch_reviews, summarize)
    _stub_parse_reviews(monkeypatch, [])

    game = _game()
    await use_case.run(game, "critic", sample_size=20)

    assert existing.summary_text == "still good"
    summarize.assert_not_awaited()
    session.add.assert_not_called()
    assert game.next_refresh_at is None  # not pushed forward on a no-op recheck


async def test_falls_back_to_first_seen_at_when_release_date_is_missing(monkeypatch):
    """A game with no resolvable release_date must still get refreshed on
    schedule, not silently excluded forever."""
    session = _session_with_existing(None)
    fetch_reviews = AsyncMock(return_value="<html>reviews</html>")
    summarize = AsyncMock(
        return_value=MagicMock(summary_text="text", input_tokens=1, output_tokens=1, model="m")
    )
    use_case = ReviewEnrichmentUseCase(session, fetch_reviews, summarize)
    _stub_parse_reviews(monkeypatch, ["quote"])

    game = _game(release_date=None, first_seen_at=_TODAY)
    await use_case.run(game, "critic", sample_size=20)

    assert game.next_refresh_at is not None
