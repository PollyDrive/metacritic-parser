from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from metacritic_game_tracker.domain.rules import IngestState
from metacritic_game_tracker.infrastructure.db.models import (
    GameORM,
    IngestStateORM,
    PipelineRunORM,
    PlatformScoreORM,
    ReviewSummaryORM,
)
from metacritic_game_tracker.infrastructure.scraper.parser import ParsedGame


async def is_cancel_requested(session: AsyncSession, run_id: int) -> bool:
    """Cooperative force-stop check (operator clicks Stop on /monitoring) —
    checked between items so a stop takes effect at the next safe checkpoint
    instead of killing mid-write."""
    result = await session.execute(
        select(PipelineRunORM.cancel_requested).where(PipelineRunORM.id == run_id)
    )
    return bool(result.scalar_one_or_none())


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
            # `platform_scores=[]` here isn't a no-op default: without it, this
            # object's very first access of `.platform_scores` happens AFTER
            # `upsert_platform_scores`'s own query has already autoflushed this
            # pending INSERT (assigning it a real id) — a persistent-but-never-
            # loaded selectin relationship then triggers a genuine lazy load on
            # first touch, which a synchronous `.append()` can't await
            # (sqlalchemy.exc.MissingGreenlet). Assigning the collection up
            # front marks it loaded before that can happen.
            existing = GameORM(metacritic_id=parsed.metacritic_id, first_seen_at=now, platform_scores=[])
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
                # `platform_scores` is lazy="selectin" — eagerly loaded once
                # when the game was fetched, then cached. session.add() alone
                # never updates that already-cached Python-side list, so any
                # code reading game.platform_scores right after this call
                # (e.g. review-refresh's per-platform sampling) would see it
                # as empty for a brand-new game even though the row was just
                # written.
                game.platform_scores.append(row)
            row.metascore = p.metascore
            row.userscore = p.userscore
            row.updated_at = now

    async def get_by_id(self, game_id: int) -> GameORM | None:
        return await self._session.get(GameORM, game_id)

    async def get_by_slug(self, slug: str) -> GameORM | None:
        result = await self._session.execute(
            select(GameORM).where(GameORM.metacritic_slug == slug)
        )
        return result.scalar_one_or_none()

    async def filter_known_slugs(self, slugs: list[str]) -> set[str]:
        """Cheap pre-fetch check for the ingest fallback decision (FR-002/003) —
        which of these listing-page slugs are already in the catalog, without
        touching any game's detail page."""
        if not slugs:
            return set()
        result = await self._session.execute(
            select(GameORM.metacritic_slug).where(GameORM.metacritic_slug.in_(slugs))
        )
        return set(result.scalars().all())

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
            # A game with N platforms otherwise contributes N rows to this
            # join — GROUP BY collapses that back to one row per game *before*
            # LIMIT is applied, so a page never comes back short just because
            # some of its games are multi-platform. Reuse the platform-filter
            # join above when present instead of adding a second one.
            if not platform:
                stmt = stmt.outerjoin(PlatformScoreORM)
            stmt = stmt.group_by(GameORM.id).order_by(
                func.max(PlatformScoreORM.metascore).desc().nulls_last(), GameORM.id.desc()
            )
        else:
            # A future release_date (an announced/unreleased title) must not
            # outrank an actually-recent release just because it's a larger
            # date value — rank it like an unknown release_date instead
            # (sinks to the bottom via nulls_last), not "the newest thing".
            today = datetime.now(UTC).date()
            released_date = case((GameORM.release_date <= today, GameORM.release_date), else_=None)
            stmt = stmt.order_by(released_date.desc().nulls_last(), GameORM.id.desc())

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
                see_all_next_page=1,
                updated_at=datetime.now(UTC),
            )
            self._session.add(state)
        return state

    async def advance(self, new_state: IngestState) -> None:
        row = await self.get()
        row.current_day = new_state.current_day
        row.day_processed_count = new_state.day_processed_count
        row.see_all_next_page = new_state.see_all_next_page
        row.updated_at = datetime.now(UTC)
