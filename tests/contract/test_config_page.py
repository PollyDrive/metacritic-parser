from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from metacritic_game_tracker.infrastructure.db.models import RuntimeConfigORM
from metacritic_game_tracker.infrastructure.web.app import create_app
from metacritic_game_tracker.infrastructure.web.routes_config import get_config_session

os.environ.setdefault("MONITORING_USERNAME", "test-op")
os.environ.setdefault("MONITORING_PASSWORD", "test-pass")

AUTH = ("test-op", "test-pass")


def _row(key, value, value_type, min_value=None, max_value=None):
    return RuntimeConfigORM(
        key=key, value=value, value_type=value_type, min_value=min_value, max_value=max_value
    )


def _session_with(rows):
    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    session.execute.return_value = result

    by_key = {row.key: row for row in rows}

    async def _get(model, key):
        return by_key.get(key)

    session.get.side_effect = _get
    return session


@pytest.fixture
def app():
    return create_app()


def test_pipeline_enable_switches_are_not_shown_here_anymore(app):
    """They moved to /monitoring, right on each pipeline's own card, so an
    operator can see 'is it on' and 'is it running' in one place."""
    rows = [
        _row("ingest.enabled", "true", "bool"),
        _row("enrichment.review_summary_enabled", "true", "bool"),
        _row("enrichment.playthrough_enabled", "false", "bool"),
        _row("ingest.games_per_run", "20", "int", 1, 100),
    ]
    session = _session_with(rows)
    app.dependency_overrides[get_config_session] = lambda: session
    test_client = TestClient(app)

    response = test_client.get("/monitoring/config", auth=AUTH)

    assert response.status_code == 200
    assert "ingest.enabled" not in response.text
    assert "enrichment.review_summary_enabled" not in response.text
    assert "enrichment.playthrough_enabled" not in response.text
    assert "ingest.games_per_run" in response.text


def test_valid_change_is_persisted_and_redirects(app):
    row = _row("ingest.games_per_run", "20", "int", 1, 100)
    session = _session_with([row])
    app.dependency_overrides[get_config_session] = lambda: session
    test_client = TestClient(app)

    response = test_client.post(
        "/monitoring/config",
        data={"ingest.games_per_run": "5"},
        auth=AUTH,
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert row.value == "5"
    assert row.updated_by == "test-op"
    session.commit.assert_awaited_once()
    session.rollback.assert_not_awaited()


def test_out_of_range_value_is_rejected_and_leaves_stored_value_untouched(app):
    """A request_delay_seconds of 0 would DoS Metacritic — must be unreachable (FR-026)."""
    row = _row("scraper.request_delay_seconds", "1.5", "float", 0.5, 30)
    session = _session_with([row])
    app.dependency_overrides[get_config_session] = lambda: session
    test_client = TestClient(app)

    response = test_client.post(
        "/monitoring/config", data={"scraper.request_delay_seconds": "0"}, auth=AUTH
    )

    assert response.status_code == 422
    assert row.value == "1.5"
    session.commit.assert_not_awaited()
    session.rollback.assert_awaited_once()


def test_a_non_numeric_value_is_rejected_with_422_not_a_crash(app):
    """Regression: a malformed value used to raise a bare, uncaught ValueError
    from RuntimeConfig.set() — a crafted or buggy request would 500 instead
    of getting a clean per-field error."""
    row = _row("ingest.games_per_run", "20", "int", 1, 100)
    session = _session_with([row])
    app.dependency_overrides[get_config_session] = lambda: session
    test_client = TestClient(app)

    response = test_client.post(
        "/monitoring/config", data={"ingest.games_per_run": "garbage"}, auth=AUTH
    )

    assert response.status_code == 422
    assert row.value == "20"
    session.commit.assert_not_awaited()
    session.rollback.assert_awaited_once()


def test_unknown_key_is_rejected_and_nothing_is_persisted(app):
    row = _row("ingest.games_per_run", "20", "int", 1, 100)
    session = _session_with([row])
    app.dependency_overrides[get_config_session] = lambda: session
    test_client = TestClient(app)

    response = test_client.post("/monitoring/config", data={"some.unknown.key": "value"}, auth=AUTH)

    assert response.status_code == 422
    session.commit.assert_not_awaited()
    session.rollback.assert_awaited_once()
