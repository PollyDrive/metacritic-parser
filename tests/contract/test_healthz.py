from __future__ import annotations

from fastapi.testclient import TestClient

from metacritic_game_tracker.infrastructure.web.app import create_app


def test_healthz_returns_200_without_auth():
    """nginx (deploy/nginx/metacritic-game-tracker.conf) proxies /healthz
    outside the /monitoring basic-auth zone — it must respond without
    credentials and without touching the DB, so it stays a cheap liveness
    check rather than a second readiness probe."""
    test_client = TestClient(create_app())

    response = test_client.get("/healthz")

    assert response.status_code == 200
