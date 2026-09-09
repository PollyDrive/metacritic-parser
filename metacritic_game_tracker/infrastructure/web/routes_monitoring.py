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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from metacritic_game_tracker.infrastructure.config.runtime import RuntimeConfig
from metacritic_game_tracker.infrastructure.db.models import PipelineRunORM, RunRequestORM
from metacritic_game_tracker.infrastructure.db.session import session_scope
from metacritic_game_tracker.infrastructure.web.auth import require_operator

router = APIRouter()

DEFAULT_POLL_INTERVAL_SECONDS = 5
ALLOWED_POLL_INTERVALS_SECONDS = {5, 30, 60, 300}

KNOWN_KINDS = ("ingest", "review_refresh", "playthrough")

RunState = tuple[int, str, str]

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
            run_id, status, _ = state
            payload = {"id": run_id, "stage": stage, "status": status}
            lines.append(f"data: {json.dumps(payload)}\n\n")
    return lines, updated


async def get_monitoring_session() -> AsyncSession:
    async with session_scope() as session:
        yield session


def _format_run(r: PipelineRunORM) -> dict:
    started = r.started_at.astimezone(_TZ_DISPLAY).strftime("%Y-%m-%d %H:%M:%S UTC+8") if r.started_at else ""
    finished = r.finished_at.astimezone(_TZ_DISPLAY).strftime("%Y-%m-%d %H:%M:%S UTC+8") if r.finished_at else ""
    return {
        "stage": r.stage,
        "status": r.status,
        "started_at": started,
        "finished_at": finished,
        "items_in": r.items_in,
        "items_accepted": r.items_accepted,
        "items_rejected": r.items_rejected,
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
    pipelines = [{"kind": kind, "latest": latest_by_stage.get(kind)} for kind in KNOWN_KINDS]

    history_result = await session.execute(
        select(PipelineRunORM).order_by(PipelineRunORM.started_at.desc()).limit(20)
    )
    runs = [_format_run(r) for r in history_result.scalars().all()]

    return request.app.state.templates.TemplateResponse(
        request, "monitoring.html", {"runs": runs, "pipelines": pipelines}
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
            latest_by_stage = {r.stage: (r.id, r.status, r.stage) for r in result.scalars().all()}
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
        select(PipelineRunORM.id).where(PipelineRunORM.stage == kind, PipelineRunORM.status == "running")
    )
    if running.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail=f"A {kind} run is already in progress")

    pending = await session.execute(
        select(RunRequestORM.id).where(RunRequestORM.kind == kind, RunRequestORM.picked_up_at.is_(None))
    )
    if pending.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail=f"A {kind} run request is already pending")

    request_row = RunRequestORM(requested_at=datetime.now(UTC), kind=kind)
    session.add(request_row)
    await session.commit()
    await session.refresh(request_row)
    return JSONResponse(status_code=202, content={"id": request_row.id, "kind": kind})
