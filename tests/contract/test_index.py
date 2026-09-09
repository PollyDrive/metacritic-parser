from __future__ import annotations

from fastapi.testclient import TestClient

from metacritic_game_tracker.infrastructure.web.app import create_app


def test_root_lists_links_to_every_page():
    client = TestClient(create_app())

    response = client.get("/")

    assert response.status_code == 200
    assert 'href="/games"' in response.text
    assert 'href="/monitoring"' in response.text
    assert 'href="/monitoring/config"' in response.text
