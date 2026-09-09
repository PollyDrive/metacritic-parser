"""Operator console — runtime_config settings page (contracts/web-ui.md, US5).

All-or-nothing save: any invalid submitted value rolls back every change in
the same request, so a partial retune can't leave the pipeline half-configured.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from metacritic_game_tracker.infrastructure.config.runtime import (
    InvalidValueError,
    RuntimeConfig,
    UnknownConfigKeyError,
    ValueOutOfRangeError,
)
from metacritic_game_tracker.infrastructure.db.session import session_scope
from metacritic_game_tracker.infrastructure.web.auth import require_operator
from metacritic_game_tracker.infrastructure.web.config_labels import RU_LABELS, RU_WHY

router = APIRouter()


async def get_config_session() -> AsyncSession:
    async with session_scope() as session:
        yield session


@router.get("/monitoring/config", response_class=HTMLResponse)
async def show_config(
    request: Request,
    session: AsyncSession = Depends(get_config_session),
    operator: str = Depends(require_operator),
):
    config = RuntimeConfig(session)
    rows = await config.list_all()
    return request.app.state.templates.TemplateResponse(
        request, "config.html", {"rows": rows, "errors": {}, "labels": RU_LABELS, "why": RU_WHY}
    )


@router.post("/monitoring/config")
async def save_config(
    request: Request,
    session: AsyncSession = Depends(get_config_session),
    operator: str = Depends(require_operator),
):
    form = await request.form()
    config = RuntimeConfig(session)
    known_keys = {row.key for row in await config.list_all()}

    errors: dict[str, str] = {}
    for key, raw_value in form.multi_items():
        if key not in known_keys:
            errors[key] = "unknown config key"
            continue
        try:
            await config.set(key, str(raw_value), updated_by=operator)
        except (UnknownConfigKeyError, ValueOutOfRangeError, InvalidValueError) as exc:
            errors[key] = str(exc)

    if errors:
        await session.rollback()
        rows = await config.list_all()
        return request.app.state.templates.TemplateResponse(
            request,
            "config.html",
            {"rows": rows, "errors": errors, "labels": RU_LABELS, "why": RU_WHY},
            status_code=422,
        )

    await session.commit()
    return RedirectResponse(url="/monitoring/config", status_code=303)
