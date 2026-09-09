from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from metacritic_game_tracker.application.ingest import IngestGamesUseCase
from metacritic_game_tracker.domain.models import GameStub, PlatformScore
from metacritic_game_tracker.infrastructure.db.models import GameORM, IngestStateORM
from metacritic_game_tracker.infrastructure.scraper.parser import ParsedGame

_GAME_HTML = "<html>game</html>"


def _config(games_per_run=20, max_reject_ratio=0.25, critic_n=20, user_n=20, tz="UTC"):
    values = {
        "ingest.games_per_run": games_per_run,
        "reviews.critic_sample_size": critic_n,
        "reviews.user_sample_size": user_n,
    }
    float_values = {"dq.max_reject_ratio": max_reject_ratio}
    config = MagicMock()
    config.get_int = AsyncMock(side_effect=lambda k: values[k])
    config.get_float = AsyncMock(side_effect=lambda k: float_values[k])
    config.get_str = AsyncMock(return_value=tz)
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
    session.execute = AsyncMock()
    session.execute.return_value.scalars.return_value.all.return_value = []
    return IngestGamesUseCase(
        session=session,
        config=config or _config(),
        ingest_state_repo=ingest_state_repo,
        game_repo=game_repo,
        fetch_listing=AsyncMock(return_value=[GameStub(metacritic_slug="game-1", metacritic_id=None)]),
        fetch_detail=fetch_detail,
        fetch_reviews=AsyncMock(return_value="<html>reviews</html>"),
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
