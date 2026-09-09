"""IngestGamesUseCase — the hourly ingestion orchestrator.

Pipeline: select source (domain/rules.py) -> fetch listing -> list_games ->
Gate A (per detail page) -> parse -> Gate B (per record) -> upsert (dedup by
metacritic_id) -> enrich only newly-admitted or still-incomplete games ->
advance ingest_state only on a non-aborted run -> record pipeline_runs.

Fetching is injected (fetch_listing/fetch_detail/fetch_reviews) so this
orchestration is unit-testable without touching httpx or a real DB — the
collaborators (metacritic_client, GameRepository, IngestStateRepository) each
have their own tests.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from metacritic_game_tracker.domain.rules import (
    IngestState,
    NewReleasesSource,
    advance_state,
    day_key,
    plan_ingest,
    roll_over_if_new_day,
)
from metacritic_game_tracker.infrastructure.config.runtime import RuntimeConfig
from metacritic_game_tracker.infrastructure.db.models import PipelineRejectORM, PipelineRunORM
from metacritic_game_tracker.infrastructure.db.repositories import (
    GameRepository,
    IngestStateRepository,
)
from metacritic_game_tracker.infrastructure.dq import gates
from metacritic_game_tracker.infrastructure.scraper import parser

log = logging.getLogger(__name__)


def _source_name(source) -> str:
    return "new_releases" if isinstance(source, NewReleasesSource) else "see_all_newest"


class IngestGamesUseCase:
    def __init__(
        self,
        session: AsyncSession,
        config: RuntimeConfig,
        ingest_state_repo: IngestStateRepository,
        game_repo: GameRepository,
        fetch_listing,
        fetch_detail,
        fetch_reviews,
        summarize,
    ):
        self._session = session
        self._config = config
        self._ingest_state_repo = ingest_state_repo
        self._game_repo = game_repo
        self._fetch_listing = fetch_listing
        self._fetch_detail = fetch_detail
        self._fetch_reviews = fetch_reviews
        self._summarize = summarize

        from metacritic_game_tracker.application.enrichment import ReviewEnrichmentUseCase
        self._review_enrichment_use_case = ReviewEnrichmentUseCase(
            session=self._session,
            fetch_reviews=self._fetch_reviews,
            summarize=self._summarize,
        )

    async def run(self) -> PipelineRunORM:
        games_per_run = await self._config.get_int("ingest.games_per_run")
        max_reject_ratio = await self._config.get_float("dq.max_reject_ratio")
        tz = await self._config.get_str("ingest.timezone")

        state_orm = await self._ingest_state_repo.get()
        domain_state = IngestState(
            current_day=state_orm.current_day,
            day_processed_count=state_orm.day_processed_count,
            day_new_releases_done=state_orm.day_new_releases_done,
            see_all_next_page=state_orm.see_all_next_page,
        )
        today = day_key(datetime.now(UTC), tz)
        domain_state = roll_over_if_new_day(domain_state, today)
        plan = plan_ingest(domain_state)

        run_row = PipelineRunORM(
            stage="ingest",
            status="running",
            started_at=datetime.now(UTC),
            source=_source_name(plan.primary),
        )
        self._session.add(run_row)
        # Committed immediately, separately from the batch's final commit, so a
        # concurrent viewer (the monitoring page) sees "running" while the scrape
        # is still in flight rather than only ever seeing the terminal state.
        await self._session.commit()

        stubs = await self._fetch_listing(plan.primary)
        topup_used = False
        topup_count_target = 0
        if len(stubs) < games_per_run and plan.topup is not None:
            topup_used = True
            more = await self._fetch_listing(plan.topup)
            topup_count_target = len(more)
            stubs = stubs + more
        stubs = stubs[:games_per_run]

        checked = 0
        rejected = 0
        accepted_parsed = []

        for stub in stubs:
            # Committed per item (not only in the batch's final commit) so a
            # concurrent viewer — the monitoring page's SSE poll — can show
            # which game a manual run is currently processing.
            run_row.meta = {"current_item": stub.metacritic_slug}
            await self._session.commit()

            html = await self._fetch_detail(stub)
            resolved = parser.get_resolved_game(html)
            try:
                gates.check_source(resolved)
            except gates.GateSourceError as exc:
                run_row.status = "failed"
                run_row.finished_at = datetime.now(UTC)
                run_row.error_message = f"Gate A: {exc}"
                run_row.items_in = len(stubs)
                return run_row

            parsed = parser.build_parsed_game(resolved)
            checked += 1
            verdict = gates.check_record(parsed)
            if not verdict.admitted:
                rejected += 1
                self._session.add(
                    PipelineRejectORM(
                        stage="ingest",
                        item_ref=stub.metacritic_slug,
                        reason_code=verdict.reason_code,
                        created_at=datetime.now(UTC),
                    )
                )
                continue
            accepted_parsed.append(parsed)

        if checked > 0 and (rejected / checked) > max_reject_ratio:
            run_row.status = "failed"
            run_row.finished_at = datetime.now(UTC)
            run_row.error_message = f"reject ratio {rejected}/{checked} exceeds {max_reject_ratio}"
            run_row.items_in = checked
            run_row.items_rejected = rejected
            return run_row

        critic_n = await self._config.get_int("reviews.critic_sample_size")
        user_n = await self._config.get_int("reviews.user_sample_size")

        primary_count = 0

        for parsed in accepted_parsed:
            run_row.meta = {"current_item": parsed.title}
            await self._session.commit()

            game, is_new = await self._game_repo.upsert(parsed)
            await self._game_repo.upsert_platform_scores(game, parsed)
            primary_count += 1

            now = datetime.now(UTC)
            refresh_due = game.next_refresh_at is not None and game.next_refresh_at <= now

            needs_critic = is_new or refresh_due or not await self._has_summary(game, "critic")
            needs_user = is_new or refresh_due or not await self._has_summary(game, "user")

            if needs_critic:
                await self._try_enrich(game, "critic", critic_n)
            if needs_user:
                await self._try_enrich(game, "user", user_n)

        new_state = advance_state(
            domain_state,
            plan,
            primary_count=primary_count,
            topup_used=topup_used,
            topup_count=topup_count_target if topup_used else 0,
        )
        await self._ingest_state_repo.advance(new_state)

        run_row.status = "completed"
        run_row.finished_at = datetime.now(UTC)
        run_row.items_in = checked
        run_row.items_accepted = len(accepted_parsed)
        run_row.items_rejected = rejected
        return run_row

    async def _has_summary(self, game, audience: str) -> bool:
        return await self._game_repo.has_review_summary(game.id, audience)

    async def _try_enrich(self, game, audience: str, sample_size: int) -> None:
        """An enrichment failure (bad/expired LLM key, timeout, quota) must never
        roll back an otherwise-successful scrape batch."""
        try:
            await self._review_enrichment_use_case.run(game, audience, sample_size)
        except Exception:
            log.exception(
                "Inline %s-review summarization failed for game_id=%s — deferred to backfill",
                audience,
                game.id,
            )
