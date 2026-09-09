"""Typed accessor over runtime_config (research.md §11) — operational knobs an
operator tunes at runtime. Values are re-read per call, never cached in-process,
so a change takes effect on the worker's next run with no restart. Bounds are
enforced here, server-side, so the check cannot be bypassed by a crafted request."""
from __future__ import annotations

import re
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from metacritic_game_tracker.infrastructure.db.models import RuntimeConfigORM

_TIME_RE = re.compile(r"^([01][0-9]|2[0-4]):[0-5][0-9]$")


class UnknownConfigKeyError(Exception):
    pass


class ValueOutOfRangeError(Exception):
    pass


class InvalidValueError(Exception):
    """The raw value doesn't parse as its declared `value_type` at all —
    distinct from ValueOutOfRangeError, which is a well-formed value outside
    its configured bounds."""


class RuntimeConfig:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def _get_row(self, key: str) -> RuntimeConfigORM:
        row = await self._session.get(RuntimeConfigORM, key)
        if row is None:
            raise UnknownConfigKeyError(key)
        return row

    async def get_str(self, key: str) -> str:
        row = await self._get_row(key)
        return row.value

    async def get_int(self, key: str) -> int:
        row = await self._get_row(key)
        return int(row.value)

    async def get_float(self, key: str) -> float:
        row = await self._get_row(key)
        return float(row.value)

    async def get_bool(self, key: str) -> bool:
        row = await self._get_row(key)
        return row.value.strip().lower() == "true"

    async def list_all(self) -> list[RuntimeConfigORM]:
        result = await self._session.execute(select(RuntimeConfigORM).order_by(RuntimeConfigORM.key))
        return list(result.scalars().all())

    async def set(self, key: str, raw_value: str, updated_by: str) -> None:
        row = await self._get_row(key)

        if row.value_type in ("int", "float"):
            try:
                numeric = float(raw_value)
            except ValueError as exc:
                raise InvalidValueError(f"{key}={raw_value!r} is not a valid number") from exc
            if row.value_type == "int" and not numeric.is_integer():
                raise InvalidValueError(f"{key}={raw_value!r} is not a valid integer")
            if row.min_value is not None and numeric < row.min_value:
                raise ValueOutOfRangeError(f"{key}={raw_value} below minimum {row.min_value}")
            if row.max_value is not None and numeric > row.max_value:
                raise ValueOutOfRangeError(f"{key}={raw_value} above maximum {row.max_value}")
        elif row.value_type == "bool":
            if raw_value.strip().lower() not in ("true", "false"):
                raise InvalidValueError(f"{key}={raw_value!r} is not 'true' or 'false'")
        elif row.value_type == "time":
            if not _TIME_RE.match(raw_value.strip()):
                raise InvalidValueError(f"{key}={raw_value!r} is not a valid HH:MM time")

        row.value = raw_value
        row.updated_by = updated_by
        row.updated_at = datetime.now(UTC)
