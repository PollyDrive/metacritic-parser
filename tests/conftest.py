from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture
def mock_session() -> AsyncMock:
    session = AsyncMock(spec=AsyncSession)
    session.execute = AsyncMock()
    # An AsyncMock's own return_value defaults to another AsyncMock, whose
    # .scalar_one_or_none() then returns an unawaited coroutine — truthy,
    # which would make is_cancel_requested (application/ingest.py,
    # application/backfill.py) see every run as cancelled. Force a plain
    # MagicMock so .scalar_one_or_none() returns a real (falsy) value.
    session.execute.return_value = MagicMock()
    session.execute.return_value.scalar_one_or_none.return_value = None
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    return session
