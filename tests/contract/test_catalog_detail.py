from __future__ import annotations

import json
from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from metacritic_game_tracker.application.catalog import GameDetail
from metacritic_game_tracker.infrastructure.db.models import GameORM, PlatformScoreORM
from metacritic_game_tracker.infrastructure.web.app import create_app
from metacritic_game_tracker.infrastructure.web.routes_catalog import get_catalog_use_case


def _game(review_summaries=None):
    game = GameORM(
        id=1, metacritic_id=1, metacritic_slug="elden-ring", title="Elden Ring",
        developer="From Software", description="A New World", video_url="https://video",
        genres=["Action RPG"], release_date=date(2022, 2, 25),
    )
    game.platform_scores = [PlatformScoreORM(platform="PS5", metascore=96, userscore=8.4)]
    game.review_summaries = review_summaries if review_summaries is not None else [
        MagicMock(audience="critic", summary_text=json.dumps({"pros": ["Great combat"], "cons": ["Slow start"]})),
        MagicMock(audience="user", summary_text=json.dumps({"pros": ["Fun with friends"], "cons": []})),
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
    assert "Great combat" in body
    assert "Fun with friends" in body
    assert "2022-02-25" in body


def test_review_summary_shows_sample_size_total_platform_and_source_link(client):
    game = _game(review_summaries=[
        MagicMock(
            audience="user", summary_text=json.dumps({"pros": ["Great combat"], "cons": []}),
            total_reviews_count=334, sampled_reviews_count=20, source_platform="PlayStation 5",
            source_url="https://www.metacritic.com/game/elden-ring/user-reviews/?platform=playstation-5",
        ),
    ])
    test_client, use_case = client
    use_case.get_game_detail = AsyncMock(return_value=GameDetail(game=game, similar_games=[]))

    response = test_client.get("/games/1")

    body = response.text
    assert "Based on 20 of 334 reviews" in body
    assert "PlayStation 5" in body
    assert 'href="https://www.metacritic.com/game/elden-ring/user-reviews/?platform=playstation-5"' in body


def test_video_and_playthrough_links_open_in_a_new_tab(client):
    """Real bug: watching a video/playthrough link navigated away from the
    detail page in the same tab, losing scroll position and catalog context —
    should open alongside it, not replace it."""
    test_client, use_case = client
    game = _game()
    game.playthrough_takeaway = MagicMock(
        video_url="https://youtube.com/watch?v=abc", takeaway_text="Great open world."
    )
    use_case.get_game_detail = AsyncMock(return_value=GameDetail(game=game, similar_games=[]))

    response = test_client.get("/games/1")

    body = response.text
    assert '<a href="https://video" target="_blank"' in body
    assert '<a href="https://youtube.com/watch?v=abc" target="_blank"' in body


def test_a_malformed_review_summary_does_not_crash_the_whole_page():
    """A pre-existing row from before the JSON-summary contract (or any future
    bad write) must degrade gracefully — the pros/cons block is skipped for
    that summary, not a 500 for the whole detail page."""
    app = create_app()
    use_case = MagicMock()
    app.dependency_overrides[get_catalog_use_case] = lambda: use_case
    test_client = TestClient(app, raise_server_exceptions=False)

    legacy_summary = MagicMock(audience="critic", summary_text="Critics love it — plain text, not JSON.")
    use_case.get_game_detail = AsyncMock(
        return_value=GameDetail(game=_game(review_summaries=[legacy_summary]), similar_games=[])
    )

    response = test_client.get("/games/1")

    assert response.status_code == 200
    assert "Elden Ring" in response.text


def test_get_game_detail_404s_for_an_unknown_id(client):
    test_client, use_case = client
    use_case.get_game_detail = AsyncMock(return_value=None)

    response = test_client.get("/games/999")

    assert response.status_code == 404
