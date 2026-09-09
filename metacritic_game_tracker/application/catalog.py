"""ListGames / GetGameDetail — US1-3 (spec.md)."""
from __future__ import annotations

from dataclasses import dataclass

from metacritic_game_tracker.infrastructure.db.models import GameORM
from metacritic_game_tracker.infrastructure.db.repositories import GameRepository


@dataclass(frozen=True)
class GameDetail:
    game: GameORM
    similar_games: list[GameORM]


class CatalogUseCase:
    def __init__(self, game_repo: GameRepository):
        self._game_repo = game_repo

    async def list_games(
        self, platform: str | None = None, q: str | None = None, sort: str | None = None
    ) -> list[GameORM]:
        return await self._game_repo.list(platform=platform, q=q, sort=sort)

    async def list_platforms(self) -> list[str]:
        return await self._game_repo.list_platforms()

    async def get_game_detail(self, game_id: int) -> GameDetail | None:
        game = await self._game_repo.get_by_id(game_id)
        if game is None:
            return None
        similar = await self._game_repo.get_similar_games(game)
        return GameDetail(game=game, similar_games=similar)
