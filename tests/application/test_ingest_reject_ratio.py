from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from metacritic_game_tracker.application.ingest import IngestGamesUseCase
from metacritic_game_tracker.domain.models import GameStub
from metacritic_game_tracker.infrastructure.db.models import IngestStateORM


def _config(max_reject_ratio=0.25):
    config = MagicMock()
    config.get_int = AsyncMock(return_value=20)
    config.get_float = AsyncMock(return_value=max_reject_ratio)
    config.get_str = AsyncMock(return_value="UTC")
    return config


def _ingest_state_repo():
    repo = MagicMock()
    repo.get = AsyncMock(
        return_value=IngestStateORM(
            id=1,
            current_day=datetime.now(UTC).date(),
            day_processed_count=0,
            day_new_releases_done=True,
            see_all_next_page=3,
            updated_at=datetime.now(UTC),
        )
    )
    repo.advance = AsyncMock()
    return repo


async def test_run_aborts_and_does_not_advance_cursor_when_reject_ratio_exceeds_the_limit(monkeypatch):
    """FR-029's second clause / research.md §14.2, found unimplemented via /speckit-analyze (E1)."""
    stubs = [GameStub(metacritic_slug=f"g{i}", metacritic_id=None) for i in range(4)]

    # 3 of 4 records fail Gate B (missing id) -> 75% reject ratio, over the 25% limit
    call_count = {"n": 0}

    def fake_resolved(html):
        call_count["n"] += 1
        return {"id": call_count["n"], "title": "G", "slug": "g", "description": "d", "platforms": [], "criticScoreSummary": {}}

    def fake_build(resolved):
        from metacritic_game_tracker.infrastructure.scraper.parser import ParsedGame

        # first record valid, rest missing metacritic_id -> Gate B rejects
        metacritic_id = resolved["id"] if resolved["id"] == 1 else None
        return ParsedGame(
            metacritic_id=metacritic_id,
            metacritic_slug="g",
            title="G",
            release_date=None,
            description="d",
            developer="Dev",
            cover_image_url="/i.jpg",
            video_url="https://v",
            genres=["Action"],
            platforms=[],
        )

    monkeypatch.setattr("metacritic_game_tracker.application.ingest.parser.get_resolved_game", fake_resolved)
    monkeypatch.setattr("metacritic_game_tracker.application.ingest.parser.build_parsed_game", fake_build)

    game_repo = MagicMock()
    game_repo.upsert = AsyncMock()

    session = AsyncMock()
    session.add = MagicMock()

    ingest_state_repo = _ingest_state_repo()
    use_case = IngestGamesUseCase(
        session=session,
        config=_config(max_reject_ratio=0.25),
        ingest_state_repo=ingest_state_repo,
        game_repo=game_repo,
        fetch_listing=AsyncMock(return_value=stubs),
        fetch_detail=AsyncMock(return_value="<html></html>"),
        fetch_reviews=AsyncMock(return_value="<html></html>"),
        summarize=AsyncMock(),
    )

    run_row = await use_case.run()

    assert run_row.status == "failed"
    game_repo.upsert.assert_not_awaited()
    ingest_state_repo.advance.assert_not_awaited()
