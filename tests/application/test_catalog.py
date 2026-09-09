from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from metacritic_game_tracker.application.catalog import CatalogUseCase
from metacritic_game_tracker.infrastructure.db.models import GameORM


def _game(id_=1, title="Elden Ring"):
    return GameORM(id=id_, metacritic_id=id_, metacritic_slug="g", title=title, genres=["Action RPG"])


async def test_list_games_returns_games_from_the_repository():
    repo = MagicMock()
    repo.list = AsyncMock(return_value=[_game(1), _game(2)])
    use_case = CatalogUseCase(repo)

    games = await use_case.list_games()

    assert len(games) == 2
    repo.list.assert_awaited_once_with(platform=None, q=None, sort=None)


async def test_list_games_passes_filter_search_sort_through():
    repo = MagicMock()
    repo.list = AsyncMock(return_value=[])
    use_case = CatalogUseCase(repo)

    await use_case.list_games(platform="PC", q="elden", sort="rating")

    repo.list.assert_awaited_once_with(platform="PC", q="elden", sort="rating")


async def test_list_platforms_delegates_to_the_repository():
    repo = MagicMock()
    repo.list_platforms = AsyncMock(return_value=["PC", "PS5"])
    use_case = CatalogUseCase(repo)

    platforms = await use_case.list_platforms()

    assert platforms == ["PC", "PS5"]


async def test_get_game_detail_returns_the_game_and_similar_games():
    game = _game(1)
    similar = [_game(2, "Hades II")]
    repo = MagicMock()
    repo.get_by_id = AsyncMock(return_value=game)
    repo.get_similar_games = AsyncMock(return_value=similar)
    use_case = CatalogUseCase(repo)

    result = await use_case.get_game_detail(1)

    assert result.game is game
    assert result.similar_games == similar


async def test_get_game_detail_returns_none_for_an_unknown_id():
    repo = MagicMock()
    repo.get_by_id = AsyncMock(return_value=None)
    use_case = CatalogUseCase(repo)

    result = await use_case.get_game_detail(999)

    assert result is None
