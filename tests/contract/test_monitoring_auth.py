from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from metacritic_game_tracker.infrastructure.web.app import create_app
from metacritic_game_tracker.infrastructure.web.routes_config import get_config_session
from metacritic_game_tracker.infrastructure.web.routes_monitoring import get_monitoring_session

os.environ.setdefault("MONITORING_USERNAME", "test-op")
os.environ.setdefault("MONITORING_PASSWORD", "test-pass")


def _mock_session():
    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    session.execute.return_value = result
    session.get.return_value = MagicMock(value="true")
    return session


@pytest.fixture
def client():
    app = create_app()
    app.dependency_overrides[get_monitoring_session] = _mock_session
    app.dependency_overrides[get_config_session] = _mock_session
    return TestClient(app)


def test_monitoring_returns_401_without_credentials(client):
    response = client.get("/monitoring")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Basic"


def test_monitoring_returns_200_with_valid_credentials(client):
    response = client.get("/monitoring", auth=("test-op", "test-pass"))

    assert response.status_code == 200


def test_monitoring_returns_401_with_wrong_credentials(client):
    response = client.get("/monitoring", auth=("test-op", "wrong-pass"))

    assert response.status_code == 401


def test_monitoring_config_returns_401_without_credentials(client):
    response = client.get("/monitoring/config")

    assert response.status_code == 401


def test_monitoring_config_returns_200_with_valid_credentials(client):
    response = client.get("/monitoring/config", auth=("test-op", "test-pass"))

    assert response.status_code == 200
