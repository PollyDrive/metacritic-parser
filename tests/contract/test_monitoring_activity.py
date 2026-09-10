from __future__ import annotations

import os
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from metacritic_game_tracker.infrastructure.db.models import (
    GameActivityEventORM,
    GameORM,
    PipelineRejectORM,
    PipelineRunORM,
)
from metacritic_game_tracker.infrastructure.web.app import create_app
from metacritic_game_tracker.infrastructure.web.routes_monitoring import get_monitoring_session

os.environ.setdefault("MONITORING_USERNAME", "test-op")
os.environ.setdefault("MONITORING_PASSWORD", "test-pass")

AUTH = ("test-op", "test-pass")


def _empty_result():
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    return result


def _result(rows):
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    return result


def _scalar_result(value):
    result = MagicMock()
    result.scalar_one.return_value = value
    return result


def _reject(run_id, reason_code, item_ref="1", detail=""):
    return PipelineRejectORM(
        stage="playthrough", run_id=run_id, item_ref=item_ref, reason_code=reason_code,
        reason_detail=detail, created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _run_with_event():
    run = PipelineRunORM(
        id=5, stage="review_refresh", status="completed",
        started_at=datetime(2026, 1, 1, tzinfo=UTC), finished_at=datetime(2026, 1, 1, tzinfo=UTC),
        items_in=1, items_accepted=1, items_rejected=0, meta={},
    )
    game = GameORM(id=9, metacritic_id=9, metacritic_slug="elden-ring", title="Elden Ring")
    event = GameActivityEventORM(
        id=1, game_id=9, run_id=5, event_type="review_refresh",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        details={"audience": "critic", "reviews_found": 20, "previous_reviews": 15, "delta": "+5"},
    )
    event.game = game
    return run, event


@pytest.fixture
def app():
    return create_app()


def test_run_history_row_carries_its_own_events_for_the_accordion(app):
    """Chosen UX: expand a run inline (accordion) rather than navigating to a
    separate page — the route must attach each run's own game_activity_events
    to it, scoped by run_id, not the global activity feed."""
    run, event = _run_with_event()
    session = AsyncMock()
    session.execute.side_effect = [
        _empty_result(),  # latest-by-stage
        _result([run]),  # run history
        _empty_result(),  # pipeline_rejects (error log + per-run detail)
        _empty_result(),  # enrichment_attempts with errors
        _result([event]),  # events for the visible runs, by run_id
        _scalar_result(3),  # total games (coverage stat)
        _scalar_result(1),  # games with a playthrough (coverage stat)
        _empty_result(),  # global activity feed
    ]
    app.dependency_overrides[get_monitoring_session] = lambda: session
    test_client = TestClient(app)

    response = test_client.get("/monitoring", auth=AUTH)

    assert response.status_code == 200
    body = response.text
    assert "Elden Ring" in body
    assert "critic" in body
    assert "+5" in body
    # links into the catalog must use the real detail route, not the slug-based one
    assert "/games/9" in body
    assert "/game/elden-ring" not in body


def test_playthrough_run_shows_youtube_calls_and_pipeline_shows_coverage(app):
    """Real user ask: how many YouTube calls did this run make, and how many
    games have a playthrough at all — both invisible before this. A call is
    derived from no_candidate_video/no_transcript rejects (search happened,
    found nothing) plus playthrough_generated events (search happened, found
    something) — budget_exhausted rejects don't count, they fire before any
    search is attempted."""
    run = PipelineRunORM(
        id=7, stage="playthrough", status="completed",
        started_at=datetime(2026, 1, 1, tzinfo=UTC), finished_at=datetime(2026, 1, 1, tzinfo=UTC),
        items_in=3, items_accepted=1, items_rejected=0, meta={},
    )
    rejects = [
        _reject(7, "no_candidate_video", item_ref="11", detail="No YouTube search result for 'Towerpulse'"),
        _reject(7, "no_transcript", item_ref="12", detail="No captions for video abc123"),
        _reject(7, "budget_exhausted", item_ref="13", detail="Daily YouTube search quota exhausted"),
    ]
    session = AsyncMock()
    session.execute.side_effect = [
        _empty_result(),  # latest-by-stage
        _result([run]),  # run history
        _result(rejects),  # pipeline_rejects (error log + per-run detail)
        _empty_result(),  # enrichment_attempts with errors
        _empty_result(),  # events for the visible runs, by run_id
        _scalar_result(10),  # total games
        _scalar_result(4),  # games with a playthrough
        _empty_result(),  # global activity feed
    ]
    app.dependency_overrides[get_monitoring_session] = lambda: session
    test_client = TestClient(app)

    response = test_client.get("/monitoring", auth=AUTH)

    assert response.status_code == 200
    body = response.text
    assert ">2<" in body  # 2 calls: the budget_exhausted reject spent no quota
    assert "4/10 games have a playthrough" in body
    # a playthrough run has no activity events at all — its rejects are its
    # detail, and they must still make the row expandable
    assert 'data-run-toggle="run-events-7"' in body
    assert "no_candidate_video" in body
    assert "No captions for video abc123" in body


def test_a_run_where_everything_was_deferred_reports_the_deferred_count(app):
    """Real bug: _format_run never carried items_deferred, so the template's
    fallback rendered it as 0 — a review_refresh run whose 296 items were all
    sitting in retry backoff displayed as In 296 / 0 / 0 / 0, reading as if
    nothing had happened rather than "everything is waiting on backoff"."""
    run = PipelineRunORM(
        id=59, stage="review_refresh", status="completed",
        started_at=datetime(2026, 1, 1, tzinfo=UTC), finished_at=datetime(2026, 1, 1, tzinfo=UTC),
        items_in=296, items_accepted=0, items_deferred=296, items_rejected=0, meta={},
    )
    session = AsyncMock()
    session.execute.side_effect = [
        _empty_result(),  # latest-by-stage
        _result([run]),  # run history
        _empty_result(),  # pipeline_rejects
        _empty_result(),  # enrichment_attempts with errors
        _empty_result(),  # events for the visible runs
        _scalar_result(0),  # total games
        _scalar_result(0),  # games with a playthrough
        _empty_result(),  # global activity feed
    ]
    app.dependency_overrides[get_monitoring_session] = lambda: session
    test_client = TestClient(app)

    response = test_client.get("/monitoring", auth=AUTH)

    assert response.status_code == 200
    assert ">296<" in response.text.replace(" ", "").replace("\n", "")


def test_run_detail_page_no_longer_exists(app):
    """Superseded by the inline accordion — a separate per-run page would be a
    second, divergent way to show the same data."""
    session = AsyncMock()
    session.execute.return_value = _empty_result()
    app.dependency_overrides[get_monitoring_session] = lambda: session
    test_client = TestClient(app)

    response = test_client.get("/monitoring/runs/5", auth=AUTH)

    assert response.status_code == 404
