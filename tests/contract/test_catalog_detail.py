from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from metacritic_game_tracker.application.catalog import GameDetail
from metacritic_game_tracker.infrastructure.db.models import GameORM
from metacritic_game_tracker.infrastructure.web.app import create_app
from metacritic_game_tracker.infrastructure.web.routes_catalog import get_catalog_use_case


def _game():
    game = GameORM(
        id=1, metacritic_id=1, metacritic_slug="elden-ring", title="Elden Ring",
        developer="From Software", description="A New World", video_url="https://video",
        genres=["Action RPG"],
    )
    game.platform_scores = [MagicMock(platform="PS5", metascore=96, userscore=8.4)]
    game.review_summaries = [
        MagicMock(audience="critic", summary_text="Critics love it."),
        MagicMock(audience="user", summary_text="Players love it too."),
    ]
    return game


@pytest.fixture
def client():
    app = create_app()
    use_case = MagicMock()
    app.dependency_overrides[get_catalog_use_case] = lambda: use_case
    return TestClient(app), use_case


def test_get_game_detail_renders_all_captured_fields(client):
    test_client, use_case = client
    use_case.get_game_detail = AsyncMock(return_value=GameDetail(game=_game(), similar_games=[]))

    response = test_client.get("/games/1")

    assert response.status_code == 200
    body = response.text
    assert "Elden Ring" in body
    assert "From Software" in body
    assert "A New World" in body
    assert "96" in body
    assert "Critics love it." in body
    assert "Players love it too." in body


def test_get_game_detail_404s_for_an_unknown_id(client):
    test_client, use_case = client
    use_case.get_game_detail = AsyncMock(return_value=None)

    response = test_client.get("/games/999")

    assert response.status_code == 404
