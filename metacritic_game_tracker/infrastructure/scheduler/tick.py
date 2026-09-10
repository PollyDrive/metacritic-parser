"""Is a run due? Anchored in the database, not an in-memory timer (research.md §3) —
a restart must not silently reset the schedule. ingest.enabled is config, not code,
so it can be retuned without a redeploy (research.md §11). Active-hours,
runs-per-hour, and a configurable day-boundary timezone were removed: the brief
fixes ingest at once per hour with no notion of "off hours," and this project
runs in a single timezone that was never actually retuned in practice."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from metacritic_game_tracker.infrastructure.config.runtime import RuntimeConfig
from metacritic_game_tracker.infrastructure.db.models import PipelineRunORM, RunRequestORM


@dataclass(frozen=True)
class TickDecision:
    should_run: bool
    reason: str
    run_request_id: int | None = None


async def decide(session: AsyncSession, config: RuntimeConfig, now: datetime) -> TickDecision:
    pending = await session.execute(
        select(RunRequestORM.id)
        .where(RunRequestORM.picked_up_at.is_(None))
        .order_by(RunRequestORM.requested_at)
        .limit(1)
    )
    request_id = pending.scalar_one_or_none()
    if request_id is not None:
        return TickDecision(True, "manual", request_id)

    if not await config.get_bool("ingest.enabled"):
        return TickDecision(False, "disabled")

    last_run_result = await session.execute(
        select(func.max(PipelineRunORM.finished_at)).where(
            PipelineRunORM.stage == "ingest", PipelineRunORM.status == "completed"
        )
    )
    last_finished_at = last_run_result.scalar_one_or_none()
    if last_finished_at is None:
        return TickDecision(True, "scheduled")

    if now - last_finished_at >= timedelta(hours=1):
        return TickDecision(True, "scheduled")
    return TickDecision(False, "not_due_yet")


async def stage_due(session: AsyncSession, stage: str, interval_hours: int, now: datetime) -> bool:
    """Is a scheduled (non-manual) run of `stage` due? review_refresh and
    playthrough don't need ingest's hourly cadence — most hourly ticks find
    nothing new to do (Decayed TTL refreshes are due every 3-7 days;
    playthrough's daily YouTube budget is spent in one burst) — so each has
    its own, coarser interval, checked against its own last completed run
    the same DB-anchored way `decide()` checks ingest's."""
    last_run_result = await session.execute(
        select(func.max(PipelineRunORM.finished_at)).where(
            PipelineRunORM.stage == stage, PipelineRunORM.status == "completed"
        )
    )
    last_finished_at = last_run_result.scalar_one_or_none()
    if last_finished_at is None:
        return True
    return now - last_finished_at >= timedelta(hours=interval_hours)


def dispatch_due(kind: str, stage_name: str, enabled: bool, due: bool) -> bool:
    """Should `stage_name`'s pipeline run this tick? A manual trigger
    (`kind == stage_name`) always proceeds, regardless of `enabled`/`due`
    (FR-009) — only the scheduled branch is gated by the pipeline's own
    enable switch and due-ness, mirroring how `decide()` already lets a
    pending manual request bypass `ingest.enabled`."""
    return kind == stage_name or (kind == "scheduled" and enabled and due)
