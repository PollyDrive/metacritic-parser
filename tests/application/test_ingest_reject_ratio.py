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


def _mock_session_execute():
    """Default every `session.execute(...)` to a scalar result of None — a
    plain AsyncMock's auto-created return value is truthy, which would make
    `is_cancel_requested` (application/ingest.py) see every run as cancelled."""
    def _result(*args, **kwargs):
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        return result

    return AsyncMock(side_effect=_result)


def _ingest_state_repo():
    repo = MagicMock()
    repo.get = AsyncMock(
        return_value=IngestStateORM(
            id=1,
            current_day=datetime.now(UTC).date(),
            day_processed_count=0,
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
    game_repo.filter_known_slugs = AsyncMock(return_value=set())

    session = AsyncMock()
    session.add = MagicMock()
    session.execute = _mock_session_execute()

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
        fetch_review_json=AsyncMock(return_value='{"data": {"totalResults": 0, "items": []}}'),
    )

    run_row = await use_case.run()

    assert run_row.status == "failed"
    game_repo.upsert.assert_not_awaited()
    ingest_state_repo.advance.assert_not_awaited()


def _gate_a_use_case(monkeypatch, ingest_state_repo):
    """A payload that Gate A rejects (missing required keys)."""
    monkeypatch.setattr(
        "metacritic_game_tracker.application.ingest.parser.get_resolved_game",
        lambda html: {"id": 1},
    )
    return IngestGamesUseCase(
        session=AsyncMock(add=MagicMock(), execute=_mock_session_execute()),
        config=_config(),
        ingest_state_repo=ingest_state_repo,
        game_repo=MagicMock(upsert=AsyncMock(), filter_known_slugs=AsyncMock(return_value=set())),
        fetch_listing=AsyncMock(return_value=[GameStub(metacritic_slug="g1", metacritic_id=None)]),
        fetch_detail=AsyncMock(return_value="<html></html>"),
        fetch_reviews=AsyncMock(return_value="<html></html>"),
        summarize=AsyncMock(),
        fetch_review_json=AsyncMock(return_value='{"data": {"totalResults": 0, "items": []}}'),
    )


async def test_a_gate_a_failure_sends_an_alert_email(monkeypatch):
    """FR-030: a source-structure break MUST be logged CRITICAL *and* alerted
    by email. This was inverted in the shipped code — nothing was sent here,
    while a routine "playthrough video has no captions" outcome did send one."""
    sent = []
    monkeypatch.setattr(
        "metacritic_game_tracker.application.ingest.send_alert_email",
        lambda subject, body: sent.append((subject, body)),
    )
    ingest_state_repo = _ingest_state_repo()
    use_case = _gate_a_use_case(monkeypatch, ingest_state_repo)

    run_row = await use_case.run()

    assert run_row.status == "failed"
    assert "Gate A" in run_row.error_message
    ingest_state_repo.advance.assert_not_awaited()
    assert len(sent) == 1
    assert "Gate A" in sent[0][0]


async def test_a_failing_alert_channel_does_not_mask_the_gate_a_failure(monkeypatch):
    """The alert is a side channel: if Resend is down or unconfigured, the run
    must still fail loudly on its own terms rather than turning an alerting
    problem into a different-looking ingestion crash."""
    def exploding_send(subject, body):
        raise RuntimeError("resend unreachable")

    monkeypatch.setattr(
        "metacritic_game_tracker.application.ingest.send_alert_email", exploding_send
    )
    ingest_state_repo = _ingest_state_repo()
    use_case = _gate_a_use_case(monkeypatch, ingest_state_repo)

    run_row = await use_case.run()

    assert run_row.status == "failed"
    assert "Gate A" in run_row.error_message
    ingest_state_repo.advance.assert_not_awaited()
