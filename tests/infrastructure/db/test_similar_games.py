from __future__ import annotations

from unittest.mock import MagicMock

from metacritic_game_tracker.infrastructure.db.models import GameORM
from metacritic_game_tracker.infrastructure.db.repositories import GameRepository


def _mock_result(games):
    result = MagicMock()
    result.scalars.return_value.unique.return_value.all.return_value = games
    return result


async def test_get_similar_games_issues_a_single_query_and_returns_genre_overlap_matches(mock_session):
    game = GameORM(id=1, metacritic_id=1, metacritic_slug="elden-ring", title="Elden Ring", genres=["Action RPG"])
    other = GameORM(id=2, metacritic_id=2, metacritic_slug="hades", title="Hades", genres=["Action RPG"])
    mock_session.execute.return_value = _mock_result([other])
    repo = GameRepository(mock_session)

    result = await repo.get_similar_games(game)

    assert mock_session.execute.await_count == 1
    assert result == [other]


async def test_get_similar_games_returns_empty_when_game_has_no_genres(mock_session):
    game = GameORM(id=1, metacritic_id=1, metacritic_slug="mystery", title="Mystery Game", genres=[])
    repo = GameRepository(mock_session)

    result = await repo.get_similar_games(game)

    assert result == []
    mock_session.execute.assert_not_awaited()
