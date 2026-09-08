from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

LOGS_DIR = Path(os.environ.get("LOGS_DIR", "logs"))
LOGS_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOGS_DIR / "app.log"),
    ],
)
log = logging.getLogger(__name__)


async def main() -> None:
    log.info("metacritic-game-tracker started")


if __name__ == "__main__":
    asyncio.run(main())
