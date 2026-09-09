from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from metacritic_game_tracker.domain.rules import IngestState
from metacritic_game_tracker.infrastructure.db.models import (
    GameORM,
    IngestStateORM,
    PlatformScoreORM,
    ReviewSummaryORM,
)
from metacritic_game_tracker.infrastructure.scraper.parser import ParsedGame


class GameRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def upsert(self, parsed: ParsedGame) -> tuple[GameORM, bool]:
        """Insert a new game or update the existing row keyed on metacritic_id
        (research.md §10) — never on the slug, which can change over time."""
        result = await self._session.execute(
            select(GameORM).where(GameORM.metacritic_id == parsed.metacritic_id)
        )
        existing = result.scalar_one_or_none()
        is_new = existing is None
        now = datetime.now(UTC)

        if existing is None:
            existing = GameORM(metacritic_id=parsed.metacritic_id, first_seen_at=now)
            self._session.add(existing)

        existing.metacritic_slug = parsed.metacritic_slug
        existing.title = parsed.title
        existing.cover_image_url = parsed.cover_image_url
        existing.developer = parsed.developer
        existing.description = parsed.description
        existing.video_url = parsed.video_url
        existing.release_date = parsed.release_date
        existing.genres = parsed.genres
        existing.last_updated_at = now

        return existing, is_new

    async def upsert_platform_scores(self, game: GameORM, parsed: ParsedGame) -> None:
        result = await self._session.execute(
            select(PlatformScoreORM).where(PlatformScoreORM.game_id == game.id)
        )
        by_platform = {row.platform: row for row in result.scalars().all()}
        now = datetime.now(UTC)
        for p in parsed.platforms:
            row = by_platform.get(p.platform)
            if row is None:
                row = PlatformScoreORM(game_id=game.id, platform=p.platform)
                self._session.add(row)
            row.metascore = p.metascore
            row.userscore = p.userscore
            row.updated_at = now

    async def get_by_id(self, game_id: int) -> GameORM | None:
        return await self._session.get(GameORM, game_id)

    async def has_review_summary(self, game_id: int, audience: str) -> bool:
        result = await self._session.execute(
            select(ReviewSummaryORM.id).where(
                ReviewSummaryORM.game_id == game_id, ReviewSummaryORM.audience == audience
            )
        )
        return result.scalar_one_or_none() is not None

    async def list(
        self,
        platform: str | None = None,
        q: str | None = None,
        sort: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[GameORM]:
        stmt = select(GameORM)
        if platform:
            stmt = stmt.join(PlatformScoreORM).where(PlatformScoreORM.platform == platform)
        if q:
            stmt = stmt.where(GameORM.title.ilike(f"%{q}%"))
        if sort == "rating":
            stmt = stmt.outerjoin(PlatformScoreORM).order_by(
                PlatformScoreORM.metascore.desc().nulls_last(), GameORM.id.desc()
            )
        else:
            stmt = stmt.order_by(GameORM.id.desc())
            
        stmt = stmt.limit(limit).offset(offset)
        result = await self._session.execute(stmt)
        return list(result.scalars().unique().all())

    async def count_list(
        self,
        platform: str | None = None,
        q: str | None = None,
    ) -> int:
        from sqlalchemy import func
        stmt = select(func.count(GameORM.id.distinct()))
        if platform:
            stmt = stmt.join(PlatformScoreORM).where(PlatformScoreORM.platform == platform)
        if q:
            stmt = stmt.where(GameORM.title.ilike(f"%{q}%"))
        result = await self._session.execute(stmt)
        return result.scalar_one()

    async def list_platforms(self) -> list[str]:
        """Distinct platform names actually present in the catalog — the filter
        select is populated from this, never from a hardcoded list."""
        result = await self._session.execute(
            select(PlatformScoreORM.platform).distinct().order_by(PlatformScoreORM.platform)
        )
        return list(result.scalars().all())

    async def get_similar_games(self, game: GameORM, limit: int = 6) -> list[GameORM]:
        """research.md §4: other catalog games sharing at least one genre, ordered
        by Metascore — a single indexed array-overlap query, never one per candidate."""
        if not game.genres:
            return []
        stmt = (
            select(GameORM)
            .where(GameORM.genres.overlap(game.genres))
            .where(GameORM.id != game.id)
            .outerjoin(PlatformScoreORM)
            .order_by(PlatformScoreORM.metascore.desc().nulls_last())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().unique().all())


class IngestStateRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get(self) -> IngestStateORM:
        state = await self._session.get(IngestStateORM, 1)
        if state is None:
            # UTC, not date.today() (server-local) — must agree with domain/rules.py's
            # day_key(), or the very first run rolls over immediately (caught by a
            # flaky test that only failed when local time and UTC disagree on the date).
            state = IngestStateORM(
                id=1,
                current_day=datetime.now(UTC).date(),
                day_processed_count=0,
                day_new_releases_done=False,
                see_all_next_page=1,
                updated_at=datetime.now(UTC),
            )
            self._session.add(state)
        return state

    async def advance(self, new_state: IngestState) -> None:
        row = await self.get()
        row.current_day = new_state.current_day
        row.day_processed_count = new_state.day_processed_count
        row.day_new_releases_done = new_state.day_new_releases_done
        row.see_all_next_page = new_state.see_all_next_page
        row.updated_at = datetime.now(UTC)
