from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from metacritic_game_tracker.infrastructure.web.app import create_app
from metacritic_game_tracker.infrastructure.web.routes_monitoring import get_monitoring_session

os.environ.setdefault("MONITORING_USERNAME", "test-op")
os.environ.setdefault("MONITORING_PASSWORD", "test-pass")

AUTH = ("test-op", "test-pass")


def _session(run_row):
    session = AsyncMock()
    session.get.return_value = run_row
    return session


@pytest.fixture
def app():
    return create_app()


def test_stop_run_flags_a_running_run_and_returns_202(app):
    run_row = MagicMock(id=7, status="running", cancel_requested=False)
    session = _session(run_row)
    app.dependency_overrides[get_monitoring_session] = lambda: session
    test_client = TestClient(app)

    response = test_client.post("/monitoring/runs/7/stop", auth=AUTH)

    assert response.status_code == 202
    assert run_row.cancel_requested is True
    session.commit.assert_awaited_once()


def test_stop_run_returns_404_for_an_unknown_run(app):
    session = _session(None)
    app.dependency_overrides[get_monitoring_session] = lambda: session
    test_client = TestClient(app)

    response = test_client.post("/monitoring/runs/999/stop", auth=AUTH)

    assert response.status_code == 404
    session.commit.assert_not_awaited()


def test_stop_run_returns_409_when_the_run_is_not_running(app):
    run_row = MagicMock(id=7, status="completed", cancel_requested=False)
    session = _session(run_row)
    app.dependency_overrides[get_monitoring_session] = lambda: session
    test_client = TestClient(app)

    response = test_client.post("/monitoring/runs/7/stop", auth=AUTH)

    assert response.status_code == 409
    assert run_row.cancel_requested is False
    session.commit.assert_not_awaited()
