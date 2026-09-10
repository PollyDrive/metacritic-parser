from __future__ import annotations

import re
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from metacritic_game_tracker.application.catalog import PaginatedGames
from metacritic_game_tracker.infrastructure.db.models import GameORM, PlatformScoreORM
from metacritic_game_tracker.infrastructure.web.app import create_app
from metacritic_game_tracker.infrastructure.web.routes_catalog import get_catalog_use_case


def _game(id_, title, platform):
    game = GameORM(id=id_, metacritic_id=id_, metacritic_slug=title.lower(), title=title, genres=[])
    game.cover_image_url = None
    game.platform_scores = [PlatformScoreORM(platform=platform, metascore=80, userscore=8.0)]
    return game


def _paginated(games):
    return PaginatedGames(games=games, total_count=len(games), total_pages=1, current_page=1)


@pytest.fixture
def client():
    app = create_app()
    use_case = MagicMock()
    use_case.list_platforms = AsyncMock(return_value=["PC", "PS5"])
    app.dependency_overrides[get_catalog_use_case] = lambda: use_case
    return TestClient(app), use_case


def test_platform_query_param_is_passed_through_to_the_use_case(client):
    test_client, use_case = client
    use_case.list_games = AsyncMock(return_value=_paginated([_game(1, "Elden Ring", "PC")]))

    response = test_client.get("/games", params={"platform": "PC"})

    assert response.status_code == 200
    use_case.list_games.assert_awaited_once_with(platform="PC", q=None, sort="rating", page=1, page_size=20)
    assert "Elden Ring" in response.text


def test_platform_filter_is_a_select_populated_from_catalog_platforms_not_a_free_text_input(client):
    """Platforms in the filter come from what's actually in the catalog — never
    a hardcoded list, and never free text a visitor could mistype."""
    test_client, use_case = client
    use_case.list_games = AsyncMock(return_value=_paginated([]))
    use_case.list_platforms = AsyncMock(return_value=["PC", "PS5", "Xbox Series X"])

    response = test_client.get("/games")

    assert response.status_code == 200
    assert re.search(r'<select[^>]*name="platform"', response.text)
    assert 'type="text" name="platform"' not in response.text
    assert '<option value="PC"' in response.text
    assert '<option value="PS5"' in response.text
    assert '<option value="Xbox Series X"' in response.text


def test_selected_platform_option_is_marked_selected(client):
    test_client, use_case = client
    use_case.list_games = AsyncMock(return_value=_paginated([]))
    use_case.list_platforms = AsyncMock(return_value=["PC", "PS5"])

    response = test_client.get("/games", params={"platform": "PS5"})

    assert '<option value="PS5" selected>' in response.text
