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

import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from metacritic_game_tracker.domain.rules import (
    IngestState,
    NewReleasesSource,
    SeeAllSource,
    advance_state,
    day_key,
    roll_over_if_new_day,
)
from metacritic_game_tracker.infrastructure.alerting.email import send_alert_email
from metacritic_game_tracker.infrastructure.config.runtime import RuntimeConfig
from metacritic_game_tracker.infrastructure.db.models import PipelineRejectORM, PipelineRunORM
from metacritic_game_tracker.infrastructure.db.repositories import (
    GameRepository,
    IngestStateRepository,
    is_cancel_requested,
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
        fetch_review_json,
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
        from metacritic_game_tracker.infrastructure.llm.cost import get_cost_usd
        self._review_enrichment_use_case = ReviewEnrichmentUseCase(
            session=self._session,
            fetch_reviews=self._fetch_reviews,
            summarize=self._summarize,
            fetch_review_json=fetch_review_json,
            get_cost_usd=lambda model, i, o: get_cost_usd(self._session, model, i, o),
        )

    async def run(self) -> PipelineRunORM:
        games_per_run = await self._config.get_int("ingest.games_per_run")
        max_reject_ratio = await self._config.get_float("dq.max_reject_ratio")

        state_orm = await self._ingest_state_repo.get()
        domain_state = IngestState(
            current_day=state_orm.current_day,
            day_processed_count=state_orm.day_processed_count,
            see_all_next_page=state_orm.see_all_next_page,
        )
        today = day_key(datetime.now(UTC), "UTC")
        domain_state = roll_over_if_new_day(domain_state, today)

        # FR-002/003: every run tries New Releases first; only when it has zero
        # games not already in the catalog does this run fall back to See All
        # at the stored forward-only cursor.
        new_release_stubs = await self._fetch_listing(NewReleasesSource())
        known_slugs = await self._game_repo.filter_known_slugs(
            [s.metacritic_slug for s in new_release_stubs]
        )
        unseen_stubs = [s for s in new_release_stubs if s.metacritic_slug not in known_slugs]

        used_fallback = len(unseen_stubs) == 0
        if used_fallback:
            source = SeeAllSource(page=domain_state.see_all_next_page)
            stubs = await self._fetch_listing(source)
        else:
            source = NewReleasesSource()
            # Only the not-yet-known ones — already-known games here have
            # their own freshness mechanism (review_refresh's Decayed TTL,
            # detail_backfill); re-fetching/re-upserting all ~20 New
            # Releases slugs every tick just because one was new wasted a
            # scrape per game per run on data nothing here actually needed.
            stubs = unseen_stubs

        run_row = PipelineRunORM(
            stage="ingest",
            status="running",
            started_at=datetime.now(UTC),
            source=_source_name(source),
        )
        self._session.add(run_row)
        # Committed immediately, separately from the batch's final commit, so a
        # concurrent viewer (the monitoring page) sees "running" while the scrape
        # is still in flight rather than only ever seeing the terminal state.
        await self._session.commit()

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

            if await is_cancel_requested(self._session, run_row.id):
                return self._mark_cancelled(run_row, checked, rejected)

            try:
                html = await self._fetch_detail(stub)
            except Exception as exc:
                log.warning("Failed to fetch detail for %s: %s", stub.metacritic_slug, exc)
                rejected += 1
                self._session.add(
                    PipelineRejectORM(
                        stage="ingest",
                        item_ref=stub.metacritic_slug,
                        reason_code="fetch_error",
                        reason_detail=str(exc),
                        created_at=datetime.now(UTC),
                    )
                )
                continue

            resolved = parser.get_resolved_game(html)
            try:
                gates.check_source(resolved)
            except gates.GateSourceError as exc:
                run_row.status = "failed"
                run_row.finished_at = datetime.now(UTC)
                run_row.error_message = f"Gate A: {exc}"
                run_row.items_in = len(stubs)
                await self._alert_source_break(stub.metacritic_slug, exc)
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
        growth_threshold = await self._config.get_int("reviews.growth_threshold")
        review_summary_enabled = await self._config.get_bool("enrichment.review_summary_enabled")

        primary_count = 0

        from metacritic_game_tracker.infrastructure.db.models import GameActivityEventORM

        for parsed in accepted_parsed:
            run_row.meta = {"current_item": parsed.title}
            await self._session.commit()

            if await is_cancel_requested(self._session, run_row.id):
                return self._mark_cancelled(run_row, checked, rejected, accepted=primary_count)

            game, is_new = await self._game_repo.upsert(parsed)
            await self._game_repo.upsert_platform_scores(game, parsed)
            primary_count += 1

            self._session.add(
                GameActivityEventORM(
                    game_id=game.id,
                    run_id=run_row.id,
                    event_type="ingest_new" if is_new else "ingest_update",
                    created_at=datetime.now(UTC),
                    details={"source": _source_name(source)}
                )
            )

            now = datetime.now(UTC)
            refresh_due = game.next_refresh_at is not None and game.next_refresh_at <= now

            if review_summary_enabled:
                needs_critic = is_new or refresh_due or not await self._has_summary(game, "critic")
                needs_user = is_new or refresh_due or not await self._has_summary(game, "user")

                if needs_critic:
                    await self._try_enrich(game, "critic", critic_n, growth_threshold, run_row.id)
                if needs_user:
                    await self._try_enrich(game, "user", user_n, growth_threshold, run_row.id)

        new_state = advance_state(domain_state, used_fallback=used_fallback, processed_count=primary_count)
        await self._ingest_state_repo.advance(new_state)

        run_row.status = "completed"
        run_row.finished_at = datetime.now(UTC)
        run_row.items_in = checked
        run_row.items_accepted = len(accepted_parsed)
        run_row.items_rejected = rejected
        return run_row

    def _mark_cancelled(
        self, run_row: PipelineRunORM, checked: int, rejected: int, accepted: int = 0
    ) -> PipelineRunORM:
        """Operator force-stop, seen at the next per-item checkpoint — same
        "no cursor movement" rule as an aborted run (Gate A / reject ratio)
        already follows, since ingest_state.advance() is simply never called."""
        run_row.status = "cancelled"
        run_row.finished_at = datetime.now(UTC)
        run_row.error_message = "Cancelled by operator"
        run_row.items_in = checked
        run_row.items_accepted = accepted
        run_row.items_rejected = rejected
        return run_row

    async def _alert_source_break(self, item_ref: str, exc: Exception) -> None:
        """FR-030: a source-structure break is logged CRITICAL (in `gates`) and
        emailed — this project has no dashboard, so the log plus this alert are
        the whole mechanism.

        Delivery runs off the event loop (the Resend client is blocking) and a
        delivery failure is swallowed deliberately: the ingestion failure is
        already recorded on `pipeline_runs` and logged CRITICAL, and turning an
        unreachable alert channel into a differently-shaped crash would hide
        the break this is meant to report.
        """
        try:
            await asyncio.to_thread(
                send_alert_email,
                f"Gate A: Metacritic payload no longer matches the expected structure ({item_ref})",
                f"item_ref={item_ref}\nreason={exc}\n\n"
                "The run was aborted and the pagination cursor was NOT advanced.",
            )
        except Exception:
            log.exception("Gate A alert email could not be delivered")

    async def _has_summary(self, game, audience: str) -> bool:
        return await self._game_repo.has_review_summary(game.id, audience)

    async def _try_enrich(
        self, game, audience: str, sample_size: int, growth_threshold: int, run_id: int
    ) -> None:
        """An enrichment failure (bad/expired LLM key, timeout, quota) must never
        roll back an otherwise-successful scrape batch."""
        try:
            await self._review_enrichment_use_case.run(
                game, audience, sample_size, growth_threshold, run_id
            )
        except Exception:
            log.exception(
                "Inline %s-review summarization failed for game_id=%s — deferred to backfill",
                audience,
                game.id,
            )
