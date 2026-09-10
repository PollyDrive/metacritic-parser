from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from metacritic_game_tracker.application.catalog import GameDetail
from metacritic_game_tracker.infrastructure.db.models import GameORM
from metacritic_game_tracker.infrastructure.web.app import create_app
from metacritic_game_tracker.infrastructure.web.routes_catalog import get_catalog_use_case


def _game(id_, title):
    game = GameORM(id=id_, metacritic_id=id_, metacritic_slug=title.lower(), title=title, genres=["Action RPG"])
    game.developer = None
    game.description = None
    game.video_url = None
    game.platform_scores = []
    game.review_summaries = []
    return game


@pytest.fixture
def client():
    app = create_app()
    use_case = MagicMock()
    app.dependency_overrides[get_catalog_use_case] = lambda: use_case
    return TestClient(app), use_case


def test_game_detail_includes_a_similar_games_section_linking_to_each_similar_game(client):
    test_client, use_case = client
    similar = _game(2, "Hades")
    use_case.get_game_detail = AsyncMock(
        return_value=GameDetail(game=_game(1, "Elden Ring"), similar_games=[similar])
    )

    response = test_client.get("/games/1")

    assert response.status_code == 200
    assert "Hades" in response.text
    assert '/games/hades"' in response.text


def test_game_detail_omits_the_similar_games_section_when_there_are_none(client):
    test_client, use_case = client
    use_case.get_game_detail = AsyncMock(
        return_value=GameDetail(game=_game(1, "Elden Ring"), similar_games=[])
    )

    response = test_client.get("/games/1")

    assert response.status_code == 200
    assert "Similar Games" not in response.text
