from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from metacritic_game_tracker.infrastructure.db.models import GameORM
from metacritic_game_tracker.infrastructure.web.app import create_app
from metacritic_game_tracker.infrastructure.web.routes_catalog import get_catalog_use_case


def _game(id_, title):
    game = GameORM(id=id_, metacritic_id=id_, metacritic_slug=title.lower(), title=title, genres=[])
    game.cover_image_url = None
    game.platform_scores = []
    return game


@pytest.fixture
def client():
    app = create_app()
    use_case = MagicMock()
    use_case.list_platforms = AsyncMock(return_value=["PC", "PS5"])
    app.dependency_overrides[get_catalog_use_case] = lambda: use_case
    return TestClient(app), use_case


def test_q_query_param_is_passed_through_to_the_use_case(client):
    test_client, use_case = client
    use_case.list_games = AsyncMock(return_value=[_game(1, "Elden Ring")])

    response = test_client.get("/games", params={"q": "elden"})

    assert response.status_code == 200
    use_case.list_games.assert_awaited_once_with(platform=None, q="elden", sort="rating")
    assert "Elden Ring" in response.text
