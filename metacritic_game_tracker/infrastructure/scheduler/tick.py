"""Is a run due? Anchored in the database, not an in-memory timer (research.md §3) —
a restart must not silently reset the schedule. Active-hours + ingest.enabled are
config, not code, so they can be retuned without a redeploy (research.md §11)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from metacritic_game_tracker.infrastructure.config.runtime import RuntimeConfig
from metacritic_game_tracker.infrastructure.db.models import PipelineRunORM, RunRequestORM


@dataclass(frozen=True)
class TickDecision:
    should_run: bool
    reason: str
    run_request_id: int | None = None


def _parse_hhmm(value: str) -> time:
    hh, mm = value.split(":")
    hh_i = int(hh)
    if hh_i == 24:
        return time(23, 59, 59)
    return time(hh_i, int(mm))


def _within_active_hours(now: datetime, start: str, end: str, tz_name: str) -> bool:
    local = now.astimezone(ZoneInfo(tz_name)).time()
    start_t, end_t = _parse_hhmm(start), _parse_hhmm(end)
    if start_t <= end_t:
        return start_t <= local <= end_t
    return local >= start_t or local <= end_t  # window wraps past midnight


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

    start = await config.get_str("ingest.active_hours_start")
    end = await config.get_str("ingest.active_hours_end")
    tz_name = await config.get_str("ingest.timezone")
    if not _within_active_hours(now, start, end, tz_name):
        return TickDecision(False, "outside_hours")

    last_run_result = await session.execute(
        select(func.max(PipelineRunORM.finished_at)).where(
            PipelineRunORM.stage == "ingest", PipelineRunORM.status == "completed"
        )
    )
    last_finished_at = last_run_result.scalar_one_or_none()
    if last_finished_at is None:
        return TickDecision(True, "scheduled")

    runs_per_hour = await config.get_int("ingest.runs_per_hour")
    interval = timedelta(hours=1) / runs_per_hour
    if now - last_finished_at >= interval:
        return TickDecision(True, "scheduled")
    return TickDecision(False, "not_due_yet")
