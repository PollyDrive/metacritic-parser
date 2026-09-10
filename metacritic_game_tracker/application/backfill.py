"""BackfillEnrichmentUseCase — derived work queue, not a status enum (research.md §7).

Completion is derived per enrichment step from whether its output row exists, so
"seen today" is never conflated with "fully enriched": a game whose review-summary
LLM call failed after ingestion is picked up here on a later run instead of being
silently and permanently incomplete.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from metacritic_game_tracker.infrastructure.config.runtime import RuntimeConfig
from metacritic_game_tracker.infrastructure.db.models import (
    EnrichmentAttemptORM,
    GameORM,
    PipelineRejectORM,
    PipelineRunORM,
    PlatformScoreORM,
    PlaythroughTakeawayORM,
    ReviewSummaryORM,
)

Step = Literal["critic_summary", "user_summary", "playthrough", "detail_fields"]

_STEP_AUDIENCE = {"critic_summary": "critic", "user_summary": "user"}


class RunBudgetExhausted(Exception):
    """A do_work callable raises this to signal a run-wide resource limit hit
    (e.g. playthrough's daily YouTube search quota) — distinct from a
    per-game failure: `run()` stops iterating immediately and records exactly
    ONE pipeline_rejects row, instead of every remaining game silently
    returning nothing with zero trace in the Errors Log."""


@dataclass
class StepOutcome:
    status: Literal["succeeded", "retrying", "abandoned"]
    attempt: EnrichmentAttemptORM | None = None
    # Most do_work callables don't return anything meaningful (implicit None) —
    # only playthrough's "no findable video" (a normal, expected outcome, not
    # an error) explicitly returns False. Defaulting True for None preserves
    # every other step's existing behavior.
    produced: bool = True


class BackfillEnrichmentUseCase:
    def __init__(self, session: AsyncSession, config: RuntimeConfig):
        self._session = session
        self._config = config

    async def process_game_step(
        self, game: GameORM, step: Step, attempt: EnrichmentAttemptORM | None, do_work
    ) -> StepOutcome:
        if attempt is not None and attempt.state == "abandoned":
            return StepOutcome("abandoned", attempt)

        if attempt is not None and attempt.next_retry_at > datetime.now(UTC):
            return StepOutcome("retrying", attempt)

        try:
            result = await do_work(game)
            produced = True if result is None else bool(result)
            return StepOutcome("succeeded", attempt, produced=produced)
        except RunBudgetExhausted:
            raise  # a run-wide stop signal, not a per-item failure — let run() handle it
        except Exception as exc:
            max_attempts = await self._config.get_int("backfill.max_attempts")
            backoff_base = await self._config.get_int("backfill.backoff_base_minutes")

            if attempt is None:
                attempt = EnrichmentAttemptORM(
                    game_id=game.id,
                    step=step,
                    attempts=1,
                    state="retrying",
                    last_attempt_at=datetime.now(UTC),
                )
                self._session.add(attempt)
            else:
                attempt.attempts += 1
                attempt.last_attempt_at = datetime.now(UTC)
            attempt.last_error = str(exc)

            if attempt.attempts >= max_attempts:
                attempt.state = "abandoned"
                self._session.add(
                    PipelineRejectORM(
                        stage="backfill",
                        item_ref=str(game.id),
                        reason_code="enrichment_abandoned",
                        reason_detail=str(exc),
                        created_at=datetime.now(UTC),
                    )
                )
                return StepOutcome("abandoned", attempt)

            attempt.next_retry_at = datetime.now(UTC) + timedelta(
                minutes=backoff_base * (2 ** (attempt.attempts - 1))
            )
            return StepOutcome("retrying", attempt)

    async def _games_missing(
        self, step: Step, limit: int | None = None
    ) -> list[tuple[GameORM, EnrichmentAttemptORM | None]]:
        if step == "detail_fields":
            # FR-028: a recoverable-field gap (description/developer/cover_image)
            # must queue for re-extraction, not sit unfilled forever — Gate B
            # computed this gap but nothing ever consumed it until now.
            stmt = select(GameORM).where(
                or_(
                    GameORM.description.is_(None), GameORM.description == "",
                    GameORM.developer.is_(None), GameORM.developer == "",
                    GameORM.cover_image_url.is_(None), GameORM.cover_image_url == "",
                )
            )
        elif step == "playthrough":
            # research.md §6: the YouTube search budget is limited, so higher-Metascore
            # (then more recent) games are searched for a playthrough first.
            stmt = (
                select(GameORM)
                .outerjoin(PlaythroughTakeawayORM)
                .outerjoin(PlatformScoreORM)
                .where(PlaythroughTakeawayORM.id.is_(None))
                .order_by(PlatformScoreORM.metascore.desc().nulls_last(), GameORM.first_seen_at.desc())
            )
        else:
            audience = _STEP_AUDIENCE[step]
            stmt = (
                select(GameORM)
                .outerjoin(
                    ReviewSummaryORM,
                    (ReviewSummaryORM.game_id == GameORM.id) & (ReviewSummaryORM.audience == audience),
                )
                .where(
                    or_(
                        ReviewSummaryORM.id.is_(None),
                        GameORM.next_refresh_at <= datetime.now(UTC)
                    )
                )
                .order_by(GameORM.first_seen_at.desc())
            )
            if limit is not None:
                stmt = stmt.limit(limit)
        result = await self._session.execute(stmt)
        games = list(result.scalars().unique().all())

        pairs = []
        for game in games:
            attempt_result = await self._session.execute(
                select(EnrichmentAttemptORM).where(
                    EnrichmentAttemptORM.game_id == game.id, EnrichmentAttemptORM.step == step
                )
            )
            pairs.append((game, attempt_result.scalar_one_or_none()))
        return pairs

    async def run(
        self, do_work_for_step, stage: str, steps: tuple[Step, ...], games_per_run: int | None = None
    ) -> PipelineRunORM:
        """`do_work_for_step(step, game)` performs the actual enrichment call.

        Owns its own `pipeline_runs` row (like `IngestGamesUseCase`), committed
        early so the monitoring page shows this pipeline as "running" while
        it's still in flight — each pipeline (review refresh, playthrough) is
        independently visible and independently triggerable, not folded into
        one shared "backfill" status.
        """
        run_row = PipelineRunORM(stage=stage, status="running", started_at=datetime.now(UTC))
        self._session.add(run_row)
        await self._session.commit()

        items_in = 0
        items_accepted = 0
        items_deferred = 0
        items_rejected = 0
        stopped_early = False
        for step in steps:
            if stopped_early:
                break
            for game, attempt in await self._games_missing(step, limit=games_per_run):
                items_in += 1
                # Committed per item (not only in the batch's final commit) so a
                # concurrent viewer — the monitoring page's SSE poll — can show
                # which game a manual run is currently processing.
                run_row.meta = {"current_item": game.title}
                await self._session.commit()
                try:
                    outcome = await self.process_game_step(
                        game, step, attempt, do_work=lambda g, s=step, rid=run_row.id: do_work_for_step(s, g, rid)
                    )
                except RunBudgetExhausted as exc:
                    self._session.add(
                        PipelineRejectORM(
                            stage=stage,
                            run_id=run_row.id,
                            item_ref=str(game.id),
                            reason_code="budget_exhausted",
                            reason_detail=str(exc),
                            created_at=datetime.now(UTC),
                        )
                    )
                    stopped_early = True
                    break
                if outcome.status == "succeeded" and outcome.produced:
                    items_accepted += 1
                elif outcome.status == "retrying":
                    items_deferred += 1
                elif outcome.status == "abandoned":
                    items_rejected += 1

        run_row.status = "completed"
        run_row.finished_at = datetime.now(UTC)
        run_row.items_in = items_in
        run_row.items_accepted = items_accepted
        run_row.items_deferred = items_deferred
        run_row.items_rejected = items_rejected
        return run_row
