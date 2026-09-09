"""ListGames / GetGameDetail — US1-3 (spec.md)."""
from __future__ import annotations

from dataclasses import dataclass

from metacritic_game_tracker.infrastructure.db.models import GameORM
from metacritic_game_tracker.infrastructure.db.repositories import GameRepository


@dataclass(frozen=True)
class GameDetail:
    game: GameORM
    similar_games: list[GameORM]


@dataclass(frozen=True)
class PaginatedGames:
    games: list[GameORM]
    total_count: int
    total_pages: int
    current_page: int


class CatalogUseCase:
    def __init__(self, game_repo: GameRepository):
        self._game_repo = game_repo

    async def list_games(
        self,
        platform: str | None = None,
        q: str | None = None,
        sort: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> PaginatedGames:
        offset = (page - 1) * page_size
        games = await self._game_repo.list(platform=platform, q=q, sort=sort, limit=page_size, offset=offset)
        total_count = await self._game_repo.count_list(platform=platform, q=q)
        total_pages = (total_count + page_size - 1) // page_size if total_count > 0 else 1
        return PaginatedGames(
            games=games,
            total_count=total_count,
            total_pages=total_pages,
            current_page=page,
        )

    async def list_platforms(self) -> list[str]:
        return await self._game_repo.list_platforms()

    async def get_game_detail(self, game_id: int) -> GameDetail | None:
        game = await self._game_repo.get_by_id(game_id)
        if game is None:
            return None
        similar = await self._game_repo.get_similar_games(game)
        return GameDetail(game=game, similar_games=similar)
