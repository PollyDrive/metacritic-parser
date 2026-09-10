from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from metacritic_game_tracker.infrastructure.web.routes_catalog import router as catalog_router
from metacritic_game_tracker.infrastructure.web.routes_config import router as config_router
from metacritic_game_tracker.infrastructure.web.routes_monitoring import (
    router as monitoring_router,
)
from metacritic_game_tracker.shared.sanitizer import mask_secrets

TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"


def _safe_fromjson(text: str) -> dict:
    """A pre-existing row from before the JSON-summary contract (or any future
    bad write) must degrade to an empty dict, not crash the whole detail page —
    the template treats a missing 'pros'/'cons' key as "nothing to show"."""
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return {}


def _mask_rendered(value):
    """Constitution (Security & Data Handling): everything surfaced through the
    web interface goes through `mask_secrets()`.

    Applied as Jinja's `finalize` hook rather than per-call at each render
    site, so a new template or a new field can't silently reintroduce a leak.
    The live path this closes: the YouTube API key travels as a `?key=` query
    param, so an httpx error carries it inside `str(exc)` — which the backfill
    retry path persists into `enrichment_attempts.last_error` and the
    monitoring Errors Log renders."""
    return mask_secrets(value) if isinstance(value, str) else value


def create_app() -> FastAPI:
    app = FastAPI(title="Metacritic Game Tracker")
    app.state.templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    app.state.templates.env.finalize = _mask_rendered
    app.state.templates.env.filters["fromjson"] = _safe_fromjson
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    app.include_router(catalog_router)
    app.include_router(monitoring_router)
    app.include_router(config_router)
    return app
