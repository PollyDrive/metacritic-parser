from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from metacritic_game_tracker.application.ingest import IngestGamesUseCase
from metacritic_game_tracker.domain.models import GameStub, PlatformScore
from metacritic_game_tracker.infrastructure.db.models import GameORM, IngestStateORM
from metacritic_game_tracker.infrastructure.scraper.parser import ParsedGame

_GAME_HTML = "<html>game</html>"


def _mock_session_execute():
    """A bare `AsyncMock().execute.return_value.scalars...` chain makes every
    accessed attribute an AsyncMock too (since the parent is one), so
    `.scalar_one_or_none()` returns a coroutine instead of a value — a real
    unittest.mock gotcha. A `side_effect` returning a fresh plain MagicMock
    per call sidesteps it, supporting both query shapes
    ReviewEnrichmentUseCase issues: no existing summary row (`scalar_one_or_none`)
    and no prior activity events (`scalars().all()`) — i.e. every game looks
    brand new, always due."""
    def _result(*args, **kwargs):
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        result.scalars.return_value.all.return_value = []
        return result

    return AsyncMock(side_effect=_result)


def _config(
    games_per_run=20, max_reject_ratio=0.25, critic_n=20, user_n=20, growth_threshold=10,
    review_summary_enabled=True,
):
    values = {
        "ingest.games_per_run": games_per_run,
        "reviews.critic_sample_size": critic_n,
        "reviews.user_sample_size": user_n,
        "reviews.growth_threshold": growth_threshold,
    }
    float_values = {"dq.max_reject_ratio": max_reject_ratio}
    bool_values = {"enrichment.review_summary_enabled": review_summary_enabled}
    config = MagicMock()
    config.get_int = AsyncMock(side_effect=lambda k: values[k])
    config.get_float = AsyncMock(side_effect=lambda k: float_values[k])
    config.get_bool = AsyncMock(side_effect=lambda k: bool_values[k])
    return config


def _parsed(metacritic_id) -> ParsedGame:
    return ParsedGame(
        metacritic_id=metacritic_id,
        metacritic_slug=f"game-{metacritic_id}",
        title=f"Game {metacritic_id}",
        release_date=None,
        description="desc",
        developer="Dev",
        cover_image_url="/img.jpg",
        video_url="https://video",
        genres=["Action"],
        platforms=[PlatformScore(platform="PC", metascore=80, userscore=8.0)],
    )


def _use_case(game_repo, ingest_state_repo, fetch_detail, config=None, summarize=None):
    session = AsyncMock()
    session.add = MagicMock()
    session.execute = _mock_session_execute()
    return IngestGamesUseCase(
        session=session,
        config=config or _config(),
        ingest_state_repo=ingest_state_repo,
        game_repo=game_repo,
        fetch_listing=AsyncMock(return_value=[GameStub(metacritic_slug="game-1", metacritic_id=None)]),
        fetch_detail=fetch_detail,
        fetch_reviews=AsyncMock(return_value="<html>reviews</html>"),
        fetch_review_json=AsyncMock(
            return_value='{"data": {"totalResults": 1, "items": [{"quote": "q"}]}}'
        ),
        summarize=summarize or AsyncMock(return_value=MagicMock(summary_text="x", input_tokens=1, output_tokens=1, model="m")),
    ), session


def _ingest_state_repo(day_new_releases_done=True, current_day=None):
    repo = MagicMock()
    repo.get = AsyncMock(
        return_value=IngestStateORM(
            id=1,
            current_day=current_day or datetime.now(UTC).date(),
            day_processed_count=0,
            day_new_releases_done=day_new_releases_done,
            see_all_next_page=1,
            updated_at=datetime.now(UTC),
        )
    )
    repo.advance = AsyncMock()
    return repo


async def test_enrichment_runs_for_a_newly_admitted_game(monkeypatch):
    parsed = _parsed(1)
    monkeypatch.setattr(
        "metacritic_game_tracker.application.ingest.parser.get_resolved_game",
        lambda html: {"id": 1, "title": "G", "slug": "g", "description": "d", "platforms": [], "criticScoreSummary": {}},
    )
    monkeypatch.setattr("metacritic_game_tracker.application.ingest.parser.build_parsed_game", lambda resolved: parsed)
    monkeypatch.setattr("metacritic_game_tracker.application.ingest.parser.parse_reviews", lambda html, sample_size: ["quote"])

    game_orm = GameORM(id=1, metacritic_id=1, metacritic_slug="game-1", title="Game 1", genres=["Action"])
    game_repo = MagicMock()
    game_repo.upsert = AsyncMock(return_value=(game_orm, True))  # is_new=True
    game_repo.upsert_platform_scores = AsyncMock()

    summarize = AsyncMock(return_value=MagicMock(summary_text="x", input_tokens=1, output_tokens=1, model="m"))
    use_case, session = _use_case(
        game_repo, _ingest_state_repo(), fetch_detail=AsyncMock(return_value=_GAME_HTML), summarize=summarize
    )

    await use_case.run()

    assert summarize.await_count == 2  # critic + user


async def test_enrichment_is_never_invoked_when_review_summary_generation_is_disabled(monkeypatch):
    """FR-003/FR-010: even a brand-new game (which would otherwise always
    qualify via the zero-base case) must not be summarized when the switch
    is off."""
    parsed = _parsed(1)
    monkeypatch.setattr(
        "metacritic_game_tracker.application.ingest.parser.get_resolved_game",
        lambda html: {"id": 1, "title": "G", "slug": "g", "description": "d", "platforms": [], "criticScoreSummary": {}},
    )
    monkeypatch.setattr("metacritic_game_tracker.application.ingest.parser.build_parsed_game", lambda resolved: parsed)
    monkeypatch.setattr("metacritic_game_tracker.application.ingest.parser.parse_reviews", lambda html, sample_size: ["quote"])

    game_orm = GameORM(id=1, metacritic_id=1, metacritic_slug="game-1", title="Game 1", genres=["Action"])
    game_repo = MagicMock()
    game_repo.upsert = AsyncMock(return_value=(game_orm, True))
    game_repo.upsert_platform_scores = AsyncMock()

    summarize = AsyncMock(return_value=MagicMock(summary_text="x", input_tokens=1, output_tokens=1, model="m"))
    use_case, session = _use_case(
        game_repo, _ingest_state_repo(), fetch_detail=AsyncMock(return_value=_GAME_HTML), summarize=summarize,
        config=_config(review_summary_enabled=False),
    )

    await use_case.run()

    summarize.assert_not_awaited()


async def test_initial_ingest_records_total_reviews_count_at_first_summarization(monkeypatch):
    """FR-002/Acceptance Scenario 3: the initial ingest pipeline itself must
    record the review count a summary was generated at — not depend on a
    later refresh pass ever running for that to happen."""
    parsed = _parsed(1)
    monkeypatch.setattr(
        "metacritic_game_tracker.application.ingest.parser.get_resolved_game",
        lambda html: {"id": 1, "title": "G", "slug": "g", "description": "d", "platforms": [], "criticScoreSummary": {}},
    )
    monkeypatch.setattr("metacritic_game_tracker.application.ingest.parser.build_parsed_game", lambda resolved: parsed)
    monkeypatch.setattr(
        "metacritic_game_tracker.application.ingest.parser.parse_reviews",
        lambda html, sample_size: ["quote 1", "quote 2"],
    )

    game_orm = GameORM(id=1, metacritic_id=1, metacritic_slug="game-1", title="Game 1", genres=["Action"])
    game_repo = MagicMock()
    game_repo.upsert = AsyncMock(return_value=(game_orm, True))
    game_repo.upsert_platform_scores = AsyncMock()

    use_case, session = _use_case(
        game_repo, _ingest_state_repo(), fetch_detail=AsyncMock(return_value=_GAME_HTML),
    )

    await use_case.run()

    from metacritic_game_tracker.infrastructure.db.models import ReviewSummaryORM
    added_summaries = [c.args[0] for c in session.add.call_args_list if isinstance(c.args[0], ReviewSummaryORM)]
    assert len(added_summaries) == 2  # critic + user
    for row in added_summaries:
        assert row.total_reviews_count == 2


async def test_a_review_summarization_failure_does_not_abort_the_whole_run(monkeypatch):
    """Caught live (T072): a bad/missing LLM API key raised from inside
    _summarize_and_store, uncaught, crashed the whole run and rolled back every
    already-scraped game in the batch. A single enrichment failure must not
    discard successful dedup/upsert work — the missing summary is picked up by
    BackfillEnrichmentUseCase on a later run."""
    parsed = _parsed(1)
    monkeypatch.setattr(
        "metacritic_game_tracker.application.ingest.parser.get_resolved_game",
        lambda html: {"id": 1, "title": "G", "slug": "g", "description": "d", "platforms": [], "criticScoreSummary": {}},
    )
    monkeypatch.setattr("metacritic_game_tracker.application.ingest.parser.build_parsed_game", lambda resolved: parsed)
    monkeypatch.setattr("metacritic_game_tracker.application.ingest.parser.parse_reviews", lambda html, sample_size: ["quote"])

    game_orm = GameORM(id=1, metacritic_id=1, metacritic_slug="game-1", title="Game 1", genres=["Action"])
    game_repo = MagicMock()
    game_repo.upsert = AsyncMock(return_value=(game_orm, True))
    game_repo.upsert_platform_scores = AsyncMock()

    summarize = AsyncMock(side_effect=RuntimeError("LLM auth failed"))
    use_case, session = _use_case(
        game_repo, _ingest_state_repo(), fetch_detail=AsyncMock(return_value=_GAME_HTML), summarize=summarize
    )

    run_row = await use_case.run()

    assert run_row.status == "completed"
    game_repo.upsert.assert_awaited_once()


async def test_run_updates_current_item_in_meta_as_it_processes_each_game(monkeypatch):
    """Same live-progress signal as BackfillEnrichmentUseCase — the monitoring
    page shows which game a manual ingest run is currently processing."""
    parsed = _parsed(1)
    monkeypatch.setattr(
        "metacritic_game_tracker.application.ingest.parser.get_resolved_game",
        lambda html: {"id": 1, "title": "G", "slug": "g", "description": "d", "platforms": [], "criticScoreSummary": {}},
    )
    monkeypatch.setattr("metacritic_game_tracker.application.ingest.parser.build_parsed_game", lambda resolved: parsed)
    monkeypatch.setattr("metacritic_game_tracker.application.ingest.parser.parse_reviews", lambda html, sample_size: ["quote"])

    game_orm = GameORM(id=1, metacritic_id=1, metacritic_slug="game-1", title="Game 1", genres=["Action"])
    game_repo = MagicMock()
    game_repo.upsert = AsyncMock(return_value=(game_orm, True))
    game_repo.upsert_platform_scores = AsyncMock()

    summarize = AsyncMock(return_value=MagicMock(summary_text="x", input_tokens=1, output_tokens=1, model="m"))
    use_case, session = _use_case(
        game_repo, _ingest_state_repo(), fetch_detail=AsyncMock(return_value=_GAME_HTML), summarize=summarize
    )

    run_row = await use_case.run()

    assert run_row.meta["current_item"] == "Game 1"
    assert session.commit.await_count >= 2  # initial "running" + at least one per item


async def test_writes_an_ingest_new_activity_event_for_a_newly_admitted_game(monkeypatch):
    parsed = _parsed(1)
    monkeypatch.setattr(
        "metacritic_game_tracker.application.ingest.parser.get_resolved_game",
        lambda html: {"id": 1, "title": "G", "slug": "g", "description": "d", "platforms": [], "criticScoreSummary": {}},
    )
    monkeypatch.setattr("metacritic_game_tracker.application.ingest.parser.build_parsed_game", lambda resolved: parsed)
    monkeypatch.setattr("metacritic_game_tracker.application.ingest.parser.parse_reviews", lambda html, sample_size: ["quote"])

    game_orm = GameORM(id=1, metacritic_id=1, metacritic_slug="game-1", title="Game 1", genres=["Action"])
    game_repo = MagicMock()
    game_repo.upsert = AsyncMock(return_value=(game_orm, True))  # is_new=True
    game_repo.upsert_platform_scores = AsyncMock()

    summarize = AsyncMock(return_value=MagicMock(summary_text="x", input_tokens=1, output_tokens=1, model="m"))
    use_case, session = _use_case(
        game_repo, _ingest_state_repo(), fetch_detail=AsyncMock(return_value=_GAME_HTML), summarize=summarize
    )

    run_row = await use_case.run()

    activity_events = [
        c.args[0] for c in session.add.call_args_list if type(c.args[0]).__name__ == "GameActivityEventORM"
    ]
    ingest_events = [e for e in activity_events if e.event_type == "ingest_new"]
    assert len(ingest_events) == 1
    assert ingest_events[0].game_id == 1
    assert ingest_events[0].run_id == run_row.id


async def test_writes_an_ingest_update_activity_event_for_an_existing_game(monkeypatch):
    parsed = _parsed(1)
    monkeypatch.setattr(
        "metacritic_game_tracker.application.ingest.parser.get_resolved_game",
        lambda html: {"id": 1, "title": "G", "slug": "g", "description": "d", "platforms": [], "criticScoreSummary": {}},
    )
    monkeypatch.setattr("metacritic_game_tracker.application.ingest.parser.build_parsed_game", lambda resolved: parsed)

    game_orm = GameORM(id=1, metacritic_id=1, metacritic_slug="game-1", title="Game 1", genres=["Action"])
    game_repo = MagicMock()
    game_repo.upsert = AsyncMock(return_value=(game_orm, False))  # is_new=False
    game_repo.upsert_platform_scores = AsyncMock()
    game_repo.has_review_summary = AsyncMock(return_value=True)

    use_case, session = _use_case(
        game_repo, _ingest_state_repo(), fetch_detail=AsyncMock(return_value=_GAME_HTML)
    )

    await use_case.run()

    activity_events = [
        c.args[0] for c in session.add.call_args_list if type(c.args[0]).__name__ == "GameActivityEventORM"
    ]
    assert len(activity_events) == 1
    assert activity_events[0].event_type == "ingest_update"


async def test_enrichment_is_skipped_for_an_already_enriched_existing_game(monkeypatch):
    """FR-024: re-ingesting an already-enriched game triggers zero LLM calls."""
    parsed = _parsed(1)
    monkeypatch.setattr(
        "metacritic_game_tracker.application.ingest.parser.get_resolved_game",
        lambda html: {"id": 1, "title": "G", "slug": "g", "description": "d", "platforms": [], "criticScoreSummary": {}},
    )
    monkeypatch.setattr("metacritic_game_tracker.application.ingest.parser.build_parsed_game", lambda resolved: parsed)

    game_orm = GameORM(id=1, metacritic_id=1, metacritic_slug="game-1", title="Game 1", genres=["Action"])
    game_repo = MagicMock()
    game_repo.upsert = AsyncMock(return_value=(game_orm, False))  # is_new=False
    game_repo.upsert_platform_scores = AsyncMock()
    game_repo.has_review_summary = AsyncMock(return_value=True)  # already has both

    summarize = AsyncMock()
    use_case, session = _use_case(
        game_repo, _ingest_state_repo(), fetch_detail=AsyncMock(return_value=_GAME_HTML), summarize=summarize
    )

    await use_case.run()

    summarize.assert_not_awaited()


async def test_a_subsequent_run_always_tops_up_from_see_all_page_one_prioritized(monkeypatch):
    """Real bug: See All's own cursor only moves forward and never revisits
    page 1, but the listing drifts (new games get added to page 1 all day) —
    a game published after the day's first run was permanently missed once
    the cursor advanced past page 1. Every later run must ALSO re-check page
    1, unconditionally (not just on shortfall), with page-1 results
    prioritized so an already-full primary batch can't starve them, and with
    duplicates (same slug from both sources) collapsed."""
    monkeypatch.setattr(
        "metacritic_game_tracker.application.ingest.parser.get_resolved_game",
        lambda html: {"id": 1, "title": "G", "slug": "g", "description": "d", "platforms": [], "criticScoreSummary": {}},
    )
    monkeypatch.setattr(
        "metacritic_game_tracker.application.ingest.parser.build_parsed_game",
        lambda resolved: _parsed(1),
    )
    monkeypatch.setattr(
        "metacritic_game_tracker.application.ingest.parser.parse_reviews", lambda html, sample_size: ["quote"]
    )

    from metacritic_game_tracker.domain.rules import SeeAllSource

    async def fetch_listing(source):
        if isinstance(source, SeeAllSource) and source.page == 1:
            return [
                GameStub(metacritic_slug="fresh-game", metacritic_id=None),
                GameStub(metacritic_slug="overlap-game", metacritic_id=None),
            ]
        return [
            GameStub(metacritic_slug="overlap-game", metacritic_id=None),  # duplicate, must collapse
            GameStub(metacritic_slug="long-tail-game", metacritic_id=None),
        ]

    game_orm = GameORM(id=1, metacritic_id=1, metacritic_slug="game-1", title="Game 1", genres=["Action"])
    game_repo = MagicMock()
    game_repo.upsert = AsyncMock(return_value=(game_orm, True))
    game_repo.upsert_platform_scores = AsyncMock()

    session = AsyncMock()
    session.add = MagicMock()
    session.execute = _mock_session_execute()

    use_case = IngestGamesUseCase(
        session=session,
        config=_config(games_per_run=2),  # smaller than the 4 candidates below
        ingest_state_repo=_ingest_state_repo(day_new_releases_done=True),
        game_repo=game_repo,
        fetch_listing=fetch_listing,
        fetch_detail=AsyncMock(return_value=_GAME_HTML),
        fetch_reviews=AsyncMock(return_value="<html>reviews</html>"),
        fetch_review_json=AsyncMock(
            return_value='{"data": {"totalResults": 1, "items": [{"quote": "q"}]}}'
        ),
        summarize=AsyncMock(return_value=MagicMock(summary_text="x", input_tokens=1, output_tokens=1, model="m")),
    )

    run_row = await use_case.run()

    # Truncated to games_per_run=2: both slots go to the deduped page-1
    # top-up (fresh-game, overlap-game) — long-tail-game is starved this run,
    # which is the intended trade-off (drift recovery takes priority).
    assert run_row.items_in == 2
    assert game_repo.upsert.await_count == 2
