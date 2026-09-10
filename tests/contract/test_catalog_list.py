from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from metacritic_game_tracker.application.catalog import PaginatedGames
from metacritic_game_tracker.infrastructure.db.models import GameORM, PlatformScoreORM
from metacritic_game_tracker.infrastructure.web.app import create_app
from metacritic_game_tracker.infrastructure.web.routes_catalog import get_catalog_use_case


def _game(id_=1, title="Elden Ring", platform="PC", metascore=96):
    game = GameORM(id=id_, metacritic_id=id_, metacritic_slug="elden-ring", title=title, genres=["Action RPG"])
    game.cover_image_url = "/cover.jpg"
    game.platform_scores = [PlatformScoreORM(platform=platform, metascore=metascore, userscore=8.4)]
    return game


def _paginated(games):
    return PaginatedGames(games=games, total_count=len(games), total_pages=1, current_page=1)


@pytest.fixture
def client():
    app = create_app()
    use_case = MagicMock()
    use_case.list_games = AsyncMock(return_value=_paginated([_game()]))
    use_case.list_platforms = AsyncMock(return_value=["PC", "PS5"])
    app.dependency_overrides[get_catalog_use_case] = lambda: use_case
    return TestClient(app), use_case


def test_get_games_returns_a_list_with_title_cover_platform_and_score(client):
    test_client, use_case = client
    response = test_client.get("/games")

    assert response.status_code == 200
    assert "Elden Ring" in response.text
    assert "PC" in response.text
    assert "96" in response.text


def test_get_games_with_no_catalog_renders_empty_state_not_an_error(client):
    test_client, use_case = client
    use_case.list_games = AsyncMock(return_value=_paginated([]))

    response = test_client.get("/games")

    assert response.status_code == 200


def test_get_games_requests_a_page_size_of_20(client):
    test_client, use_case = client

    test_client.get("/games")

    use_case.list_games.assert_awaited_once_with(
        platform=None, q=None, sort="rating", page=1, page_size=20
    )


def test_a_non_positive_page_is_rejected_with_422_not_a_crash(client):
    """A negative page produces a negative SQL OFFSET, which Postgres rejects
    with an unhandled exception (500) instead of a clean validation error."""
    test_client, use_case = client

    response = test_client.get("/games", params={"page": -1})

    assert response.status_code == 422
    use_case.list_games.assert_not_awaited()
