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


def _session(running=None, pending=None, playthrough_enabled=True):
    session = AsyncMock()

    running_result = MagicMock()
    running_result.scalars.return_value.first.return_value = running
    pending_result = MagicMock()
    pending_result.scalars.return_value.first.return_value = pending
    session.execute.side_effect = [running_result, pending_result]

    config_row = MagicMock()
    config_row.value = "true" if playthrough_enabled else "false"
    session.get.return_value = config_row

    async def _refresh(row):
        row.id = 42

    session.refresh.side_effect = _refresh
    return session


@pytest.fixture
def app():
    return create_app()


def test_post_run_inserts_a_run_request_and_returns_202(app):
    session = _session(running=None, pending=None)
    app.dependency_overrides[get_monitoring_session] = lambda: session
    test_client = TestClient(app)

    response = test_client.post("/monitoring/run", params={"kind": "ingest"}, auth=AUTH)

    assert response.status_code == 202
    assert response.json()["id"] == 42
    session.add.assert_called_once()
    session.commit.assert_awaited_once()
    added = session.add.call_args[0][0]
    assert added.kind == "ingest"


def test_post_run_defaults_to_ingest_when_kind_is_omitted(app):
    session = _session(running=None, pending=None)
    app.dependency_overrides[get_monitoring_session] = lambda: session
    test_client = TestClient(app)

    response = test_client.post("/monitoring/run", auth=AUTH)

    assert response.status_code == 202


def test_post_run_returns_409_when_that_pipeline_is_already_running(app):
    running_row = MagicMock(stage="ingest")
    session = _session(running=running_row, pending=None)
    app.dependency_overrides[get_monitoring_session] = lambda: session
    test_client = TestClient(app)

    response = test_client.post("/monitoring/run", params={"kind": "review_refresh"}, auth=AUTH)

    assert response.status_code == 409
    session.add.assert_not_called()


def test_post_run_returns_409_when_a_request_of_that_kind_is_already_pending(app):
    pending_row = MagicMock(kind="ingest")
    session = _session(running=None, pending=pending_row)
    app.dependency_overrides[get_monitoring_session] = lambda: session
    test_client = TestClient(app)

    response = test_client.post("/monitoring/run", params={"kind": "playthrough"}, auth=AUTH)

    assert response.status_code == 409
    session.add.assert_not_called()


def test_post_run_rejects_an_unknown_kind(app):
    session = _session()
    app.dependency_overrides[get_monitoring_session] = lambda: session
    test_client = TestClient(app)

    response = test_client.post("/monitoring/run", params={"kind": "nonsense"}, auth=AUTH)

    assert response.status_code == 400


def test_post_run_rejects_playthrough_when_the_feature_is_disabled(app):
    session = _session(running=None, pending=None, playthrough_enabled=False)
    app.dependency_overrides[get_monitoring_session] = lambda: session
    test_client = TestClient(app)

    response = test_client.post("/monitoring/run", params={"kind": "playthrough"}, auth=AUTH)

    assert response.status_code == 409
    session.add.assert_not_called()
