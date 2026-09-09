from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from metacritic_game_tracker.infrastructure.web.routes_catalog import router as catalog_router
from metacritic_game_tracker.infrastructure.web.routes_config import router as config_router
from metacritic_game_tracker.infrastructure.web.routes_monitoring import (
    router as monitoring_router,
)

TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"


def create_app() -> FastAPI:
    app = FastAPI(title="Metacritic Game Tracker")
    app.state.templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    app.include_router(catalog_router)
    app.include_router(monitoring_router)
    app.include_router(config_router)
    return app
