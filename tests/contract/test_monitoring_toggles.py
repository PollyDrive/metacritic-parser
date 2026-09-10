from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from metacritic_game_tracker.infrastructure.db.models import RuntimeConfigORM
from metacritic_game_tracker.infrastructure.web.app import create_app
from metacritic_game_tracker.infrastructure.web.routes_monitoring import get_monitoring_session

os.environ.setdefault("MONITORING_USERNAME", "test-op")
os.environ.setdefault("MONITORING_PASSWORD", "test-pass")

AUTH = ("test-op", "test-pass")


def _config_row(key, value):
    return RuntimeConfigORM(key=key, value=value, value_type="bool")


def _session(enabled_by_key=None, running=None, pending=None):
    """Mirrors monitoring_status's real execute() call order: latest-per-stage,
    then run history, then rejects, then attempts, then run-events, then
    activity feed — all empty by default. `session.get` answers per-key
    config lookups (the three enable switches)."""
    enabled_by_key = enabled_by_key or {}
    session = AsyncMock()

    empty_scalars = MagicMock()
    empty_scalars.scalars.return_value.all.return_value = []
    empty_scalars.scalars.return_value.unique.return_value.all.return_value = []
    session.execute.return_value = empty_scalars

    async def _get(model, key):
        if key in enabled_by_key:
            return _config_row(key, "true" if enabled_by_key[key] else "false")
        return None

    session.get.side_effect = _get
    return session


@pytest.fixture
def app():
    return create_app()


def test_monitoring_page_shows_each_pipelines_enabled_state(app):
    session = _session(enabled_by_key={
        "ingest.enabled": True,
        "enrichment.review_summary_enabled": False,
        "enrichment.playthrough_enabled": True,
    })
    app.dependency_overrides[get_monitoring_session] = lambda: session
    test_client = TestClient(app)

    response = test_client.get("/monitoring", auth=AUTH)

    assert response.status_code == 200
    # Three distinct toggle controls, one per pipeline, each reflecting its
    # own config value rather than sharing one shared state.
    assert response.text.count('data-toggle-kind="ingest"') == 1
    assert response.text.count('data-toggle-kind="review_refresh"') == 1
    assert response.text.count('data-toggle-kind="playthrough"') == 1


def test_post_toggle_persists_the_new_value_and_redirects(app):
    row = _config_row("enrichment.playthrough_enabled", "false")
    session = _session()
    session.get.side_effect = None
    session.get.return_value = row
    app.dependency_overrides[get_monitoring_session] = lambda: session
    test_client = TestClient(app)

    response = test_client.post(
        "/monitoring/toggle",
        data={"kind": "playthrough", "enabled": "true"},
        auth=AUTH,
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/monitoring"
    assert row.value == "true"
    assert row.updated_by == "test-op"
    session.commit.assert_awaited_once()


def test_post_toggle_rejects_an_unknown_kind(app):
    session = _session()
    app.dependency_overrides[get_monitoring_session] = lambda: session
    test_client = TestClient(app)

    response = test_client.post(
        "/monitoring/toggle", data={"kind": "nonsense", "enabled": "true"}, auth=AUTH
    )

    assert response.status_code == 400
    session.commit.assert_not_awaited()


def test_post_toggle_requires_auth(app):
    session = _session()
    app.dependency_overrides[get_monitoring_session] = lambda: session
    test_client = TestClient(app)

    response = test_client.post("/monitoring/toggle", data={"kind": "ingest", "enabled": "false"})

    assert response.status_code == 401
