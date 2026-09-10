"""Operator console — status endpoints (contracts/web-ui.md, US5).

Behind HTTP Basic Auth (FR-022/026). The web tier only enqueues a manual run —
it never executes ingestion itself (research.md §3); the worker process
consumes `run_requests` on its next poll.

Three independent pipelines, each independently visible and independently
triggerable: `ingest` (new games), `review_refresh` (Decayed TTL critic/user
summaries), `playthrough` (YouTube takeaways) — see scripts/run_scheduler.py.
"""
from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from metacritic_game_tracker.infrastructure.config.runtime import RuntimeConfig
from metacritic_game_tracker.infrastructure.db.models import (
    EnrichmentAttemptORM,
    GameActivityEventORM,
    GameORM,
    PipelineRejectORM,
    PipelineRunORM,
    PlaythroughTakeawayORM,
    RunRequestORM,
)
from metacritic_game_tracker.infrastructure.db.session import session_scope
from metacritic_game_tracker.infrastructure.web.auth import require_operator

router = APIRouter()

# A YouTube search actually happened iff the daily budget check passed —
# these are the two outcomes reachable only past that check (playthrough.py).
# "budget_exhausted" is NOT in this set: that reject fires *before* any search.
_SEARCH_ATTEMPTED_REASON_CODES = ("no_candidate_video", "no_transcript")

DEFAULT_POLL_INTERVAL_SECONDS = 5
ALLOWED_POLL_INTERVALS_SECONDS = {5, 30, 60, 300}

KNOWN_KINDS = ("ingest", "review_refresh", "playthrough")

RunState = tuple[int, str, str, str | None]

_TZ_DISPLAY = timezone(timedelta(hours=8))


def _resolve_poll_interval(raw: str | None) -> int:
    """Client-selectable refresh cadence (5s/30s/1m/5m), validated server-side
    against a fixed allow-list — falls back to the default rather than letting
    an arbitrary or tampered value reach `asyncio.sleep`."""
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_POLL_INTERVAL_SECONDS
    return value if value in ALLOWED_POLL_INTERVALS_SECONDS else DEFAULT_POLL_INTERVAL_SECONDS


def _stage_events(
    latest_by_stage: dict[str, RunState], last_seen_by_stage: dict[str, RunState]
) -> tuple[list[str], dict[str, RunState]]:
    """Decide the SSE lines (if any) for one poll tick, one per stage whose
    state actually changed — pure, so it's testable without a live stream.
    Three independent pipelines run sequentially within one worker tick, so
    tracking only the single globally-latest row (as an earlier version did)
    can skip an earlier stage's own transition once a later stage supersedes
    it as "most recent"; tracking every known stage's own last-seen state
    closes that gap. A stage absent from `last_seen_by_stage` (a fresh
    connection, or a pipeline that has never run) is always emitted."""
    lines: list[str] = []
    updated = dict(last_seen_by_stage)
    for stage, state in latest_by_stage.items():
        if last_seen_by_stage.get(stage) != state:
            updated[stage] = state
            run_id, status, _, current_item = state
            payload = {"id": run_id, "stage": stage, "status": status, "current_item": current_item}
            lines.append(f"data: {json.dumps(payload)}\n\n")
    return lines, updated


async def get_monitoring_session() -> AsyncSession:
    async with session_scope() as session:
        yield session


def _format_run(r: PipelineRunORM) -> dict:
    started = r.started_at.astimezone(_TZ_DISPLAY).strftime("%Y-%m-%d %H:%M:%S UTC+8") if r.started_at else ""
    finished = r.finished_at.astimezone(_TZ_DISPLAY).strftime("%Y-%m-%d %H:%M:%S UTC+8") if r.finished_at else ""
    return {
        "id": r.id,
        "stage": r.stage,
        "status": r.status,
        "started_at": started,
        "finished_at": finished,
        "items_in": r.items_in,
        "items_accepted": r.items_accepted,
        "items_rejected": r.items_rejected,
        # Was missing entirely, so the template's fallback rendered every run's
        # deferred count as 0 — hiding the single most common outcome: a run
        # where all 296 items were merely in retry backoff read as "0/0/0",
        # i.e. as if nothing had happened at all.
        "items_deferred": r.items_deferred,
        "error_message": r.error_message,
        "current_item": (r.meta or {}).get("current_item"),
    }


@router.get("/monitoring", response_class=HTMLResponse)
async def monitoring_status(
    request: Request,
    session: AsyncSession = Depends(get_monitoring_session),
    operator: str = Depends(require_operator),
):
    latest_stmt = (
        select(PipelineRunORM)
        .distinct(PipelineRunORM.stage)
        .order_by(PipelineRunORM.stage, PipelineRunORM.started_at.desc())
    )
    latest_result = await session.execute(latest_stmt)
    latest_by_stage = {r.stage: _format_run(r) for r in latest_result.scalars().all()}
    pipelines = [
        {"kind": kind, "latest": latest_by_stage.get(kind), "coverage": None} for kind in KNOWN_KINDS
    ]

    history_result = await session.execute(
        select(PipelineRunORM).order_by(PipelineRunORM.started_at.desc()).limit(20)
    )
    run_rows = history_result.scalars().all()

    # Unbounded on purpose: the previous 50-row cap silently truncated the
    # history to roughly one pipeline tick, so an operator could never see
    # what happened before it — the whole point of these two tabs.
    rejects_result = await session.execute(
        select(PipelineRejectORM).order_by(PipelineRejectORM.created_at.desc())
    )
    attempts_result = await session.execute(
        select(EnrichmentAttemptORM)
        .where(EnrichmentAttemptORM.last_error.is_not(None))
        .order_by(EnrichmentAttemptORM.last_attempt_at.desc())
    )

    all_rejects = list(rejects_result.scalars().all())

    error_log = []
    for r in all_rejects:
        error_log.append({
            "timestamp": r.created_at.astimezone(_TZ_DISPLAY).strftime("%Y-%m-%d %H:%M:%S UTC+8"),
            "sort_time": r.created_at,
            "pipeline": r.stage,
            "item_ref": r.item_ref,
            "error_message": f"[{r.reason_code}] {r.reason_detail or ''}"
        })
    for a in attempts_result.scalars().all():
        error_log.append({
            "timestamp": a.last_attempt_at.astimezone(_TZ_DISPLAY).strftime("%Y-%m-%d %H:%M:%S UTC+8"),
            "sort_time": a.last_attempt_at,
            "pipeline": a.step,
            "item_ref": f"Game ID {a.game_id}",
            "error_message": a.last_error or ""
        })

    error_log.sort(key=lambda x: x["sort_time"], reverse=True)

    # Chosen UX: expand a run inline (accordion) instead of navigating to a
    # separate page, so each visible run row carries its own events, scoped
    # by run_id — not the cross-game activity feed below.
    run_ids = [r.id for r in run_rows]
    events_by_run: dict[int, list[GameActivityEventORM]] = {}
    if run_ids:
        run_events_result = await session.execute(
            select(GameActivityEventORM)
            .where(GameActivityEventORM.run_id.in_(run_ids))
            .order_by(GameActivityEventORM.created_at.asc())
        )
        for event in run_events_result.scalars().all():
            events_by_run.setdefault(event.run_id, []).append(event)

    # A playthrough run usually produces no activity events at all (nothing was
    # found), so events alone left those rows with nothing to expand — exactly
    # the runs an operator most wants to open. Its rejects ARE its detail.
    visible_run_ids = set(run_ids)
    rejects_by_run: dict[int, list[PipelineRejectORM]] = {}
    for reject in all_rejects:
        if reject.run_id in visible_run_ids:
            rejects_by_run.setdefault(reject.run_id, []).append(reject)

    # "How many YouTube calls did this run make?" A call happened iff the run
    # either produced a takeaway (playthrough_generated event) or spent budget
    # searching and came up empty (no_candidate_video / no_transcript reject) —
    # both only reachable past the try_spend() budget check, unlike
    # budget_exhausted which fires before any search.
    youtube_calls_by_run: dict[int, int] = {}
    for run_id, rejects in rejects_by_run.items():
        spent = sum(1 for r in rejects if r.reason_code in _SEARCH_ATTEMPTED_REASON_CODES)
        if spent:
            youtube_calls_by_run[run_id] = youtube_calls_by_run.get(run_id, 0) + spent
    for run_id, events in events_by_run.items():
        generated = sum(1 for e in events if e.event_type == "playthrough_generated")
        if generated:
            youtube_calls_by_run[run_id] = youtube_calls_by_run.get(run_id, 0) + generated

    runs = []
    for r in run_rows:
        formatted = _format_run(r)
        formatted["events"] = events_by_run.get(r.id, [])
        formatted["rejects"] = [
            {
                "time": rj.created_at.astimezone(_TZ_DISPLAY).strftime("%H:%M:%S"),
                "item_ref": rj.item_ref,
                "reason_code": rj.reason_code,
                "reason_detail": rj.reason_detail or "",
            }
            for rj in rejects_by_run.get(r.id, [])
        ]
        formatted["youtube_calls"] = youtube_calls_by_run.get(r.id, 0) if r.stage == "playthrough" else None
        runs.append(formatted)

    # "How many games have a playthrough at all?" (US ask: currently invisible).
    total_games = (await session.execute(select(func.count()).select_from(GameORM))).scalar_one()
    games_with_playthrough = (
        await session.execute(select(func.count(func.distinct(PlaythroughTakeawayORM.game_id))))
    ).scalar_one()
    for pipeline in pipelines:
        if pipeline["kind"] == "playthrough":
            pipeline["coverage"] = {"covered": games_with_playthrough, "total": total_games}

    activity_result = await session.execute(
        select(GameActivityEventORM).order_by(GameActivityEventORM.created_at.desc())
    )
    activity_feed = activity_result.scalars().all()

    return request.app.state.templates.TemplateResponse(
        request, "monitoring.html", {
            "runs": runs,
            "pipelines": pipelines,
            "error_log": error_log,
            "activity_feed": activity_feed
        }
    )


@router.get("/monitoring/stream")
async def monitoring_stream(
    interval: str | None = None,
    session: AsyncSession = Depends(get_monitoring_session),
    operator: str = Depends(require_operator),
):
    poll_interval = _resolve_poll_interval(interval)

    async def event_source():
        last_seen: dict[str, RunState] = {}
        stmt = (
            select(PipelineRunORM)
            .distinct(PipelineRunORM.stage)
            .order_by(PipelineRunORM.stage, PipelineRunORM.started_at.desc())
        )
        while True:
            result = await session.execute(stmt)
            latest_by_stage = {
                r.stage: (r.id, r.status, r.stage, (r.meta or {}).get("current_item"))
                for r in result.scalars().all()
            }
            lines, last_seen = _stage_events(latest_by_stage, last_seen)
            for line in lines:
                yield line
            await asyncio.sleep(poll_interval)

    return StreamingResponse(event_source(), media_type="text/event-stream")


@router.post("/monitoring/run")
async def trigger_run(
    kind: str = "ingest",
    session: AsyncSession = Depends(get_monitoring_session),
    operator: str = Depends(require_operator),
):
    if kind not in KNOWN_KINDS:
        raise HTTPException(status_code=400, detail=f"Unknown pipeline kind: {kind}")

    if kind == "playthrough":
        config = RuntimeConfig(session)
        if not await config.get_bool("enrichment.playthrough_enabled"):
            raise HTTPException(status_code=409, detail="Playthrough enrichment is disabled")

    running = await session.execute(
        select(PipelineRunORM).where(PipelineRunORM.status == "running")
    )
    running_row = running.scalars().first()
    if running_row is not None:
        raise HTTPException(
            status_code=409,
            detail=f"Wait for the current {running_row.stage} pipeline to finish before starting a new one."
        )

    pending = await session.execute(
        select(RunRequestORM).where(RunRequestORM.picked_up_at.is_(None))
    )
    pending_row = pending.scalars().first()
    if pending_row is not None:
        raise HTTPException(
            status_code=409,
            detail=f"Wait for the pending {pending_row.kind} pipeline request to be processed."
        )

    request_row = RunRequestORM(requested_at=datetime.now(UTC), kind=kind)
    session.add(request_row)
    await session.commit()
    await session.refresh(request_row)
    return JSONResponse(status_code=202, content={"id": request_row.id, "kind": kind})
