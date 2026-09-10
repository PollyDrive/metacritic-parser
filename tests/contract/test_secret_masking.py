"""Constitution (Security & Data Handling): any text surfaced back through the
web interface MUST go through `mask_secrets()` first.

The concrete live path this closes: the YouTube Data API key travels as a
`?key=` query param, so an httpx error for a failed search carries the full
URL — including the key — in `str(exc)`. That string is persisted verbatim
into `enrichment_attempts.last_error` / `pipeline_rejects.reason_detail` by
the backfill retry path, and the monitoring Errors Log renders it.
"""
from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from metacritic_game_tracker.application.catalog import GameDetail
from metacritic_game_tracker.infrastructure.db.models import (
    EnrichmentAttemptORM,
    GameORM,
    PlatformScoreORM,
)
from metacritic_game_tracker.infrastructure.web.app import create_app
from metacritic_game_tracker.infrastructure.web.routes_catalog import get_catalog_use_case
from metacritic_game_tracker.infrastructure.web.routes_monitoring import get_monitoring_session

os.environ.setdefault("MONITORING_USERNAME", "test-op")
os.environ.setdefault("MONITORING_PASSWORD", "test-pass")

AUTH = ("test-op", "test-pass")

_LEAKED_KEY = "AIzaSy_FAKE_YOUTUBE_API_KEY_FOR_TESTING"
_LEAKY_ERROR = (
    "Client error '403 Forbidden' for url "
    f"'https://www.googleapis.com/youtube/v3/search?q=Elden+Ring&key={_LEAKED_KEY}'"
)


@pytest.fixture
def app():
    return create_app()


def _empty_result():
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    return result


def _result(rows):
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    return result


def _scalar_result(value):
    result = MagicMock()
    result.scalar_one.return_value = value
    return result


def test_a_leaked_api_key_in_an_enrichment_error_is_masked_in_the_errors_log(app):
    attempt = EnrichmentAttemptORM(
        id=1, game_id=7, step="playthrough", attempts=1, state="retrying",
        last_attempt_at=datetime(2026, 1, 1, tzinfo=UTC), last_error=_LEAKY_ERROR,
    )
    session = AsyncMock()
    session.get.return_value = MagicMock(value="true")
    session.execute.side_effect = [
        _empty_result(),  # latest-by-stage
        _empty_result(),  # run history
        _empty_result(),  # pipeline_rejects
        _result([attempt]),  # enrichment_attempts with errors
        _scalar_result(0),  # total games
        _scalar_result(0),  # games with a playthrough
        _empty_result(),  # activity feed
    ]
    app.dependency_overrides[get_monitoring_session] = lambda: session
    test_client = TestClient(app)

    response = test_client.get("/monitoring", auth=AUTH)

    assert response.status_code == 200
    assert _LEAKED_KEY not in response.text
    assert "403 Forbidden" in response.text  # the diagnostic itself still shows


def test_a_secret_in_scraped_or_generated_text_is_masked_on_the_detail_page(app):
    """Masking is applied to everything rendered, not just the one known
    error path — scraped descriptions and LLM output are untrusted too."""
    game = GameORM(
        id=1, metacritic_id=1, metacritic_slug="elden-ring", title="Elden Ring",
        developer="From Software", description=f"Contact us at {_LEAKED_KEY}",
        video_url="https://video", genres=["Action RPG"],
    )
    game.platform_scores = [PlatformScoreORM(platform="PS5", metascore=96, userscore=8.4)]
    game.review_summaries = [
        MagicMock(audience="critic", summary_text=json.dumps({"pros": [], "cons": []})),
    ]
    use_case = MagicMock()
    use_case.get_game_detail = AsyncMock(return_value=GameDetail(game=game, similar_games=[]))
    app.dependency_overrides[get_catalog_use_case] = lambda: use_case
    test_client = TestClient(app)

    response = test_client.get("/games/1")

    assert response.status_code == 200
    assert _LEAKED_KEY not in response.text
