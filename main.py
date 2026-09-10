from __future__ import annotations

import logging
import logging.handlers
import os
from pathlib import Path

import uvicorn
from dotenv import load_dotenv

from metacritic_game_tracker.application.catalog import CatalogUseCase
from metacritic_game_tracker.infrastructure.db.repositories import GameRepository
from metacritic_game_tracker.infrastructure.db.session import session_scope
from metacritic_game_tracker.infrastructure.web.app import create_app
from metacritic_game_tracker.infrastructure.web.routes_catalog import get_catalog_use_case

load_dotenv()

LOGS_DIR = Path(os.environ.get("LOGS_DIR", "logs"))
LOGS_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.handlers.RotatingFileHandler(
            LOGS_DIR / "app.log", maxBytes=10 * 1024 * 1024, backupCount=5
        ),
    ],
)
log = logging.getLogger(__name__)

app = create_app()


async def _catalog_use_case_dependency():
    async with session_scope() as session:
        yield CatalogUseCase(GameRepository(session))


app.dependency_overrides[get_catalog_use_case] = _catalog_use_case_dependency


if __name__ == "__main__":
    _port = int(os.environ.get("APP_PORT", "8080"))
    log.info("metacritic-game-tracker web tier starting on port %d", _port)
    uvicorn.run("main:app", host="0.0.0.0", port=_port)
