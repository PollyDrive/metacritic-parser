from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from metacritic_game_tracker.infrastructure.config.runtime import (
    InvalidValueError,
    RuntimeConfig,
    UnknownConfigKeyError,
    ValueOutOfRangeError,
)
from metacritic_game_tracker.infrastructure.db.models import RuntimeConfigORM


def _row(key, value, value_type, min_value=None, max_value=None):
    return RuntimeConfigORM(
        key=key, value=value, value_type=value_type, min_value=min_value, max_value=max_value
    )


def _session_returning(row):
    session = AsyncMock()
    session.get.return_value = row
    return session


async def test_get_float_coerces_stored_string_to_float():
    session = _session_returning(_row("scraper.request_delay_seconds", "1.5", "float", 0.5, 30))
    config = RuntimeConfig(session)
    assert await config.get_float("scraper.request_delay_seconds") == 1.5


async def test_get_int_coerces_stored_string_to_int():
    session = _session_returning(_row("ingest.games_per_run", "20", "int", 1, 100))
    config = RuntimeConfig(session)
    assert await config.get_int("ingest.games_per_run") == 20


async def test_get_bool_coerces_stored_string_to_bool():
    session = _session_returning(_row("ingest.enabled", "true", "bool"))
    config = RuntimeConfig(session)
    assert await config.get_bool("ingest.enabled") is True


async def test_set_rejects_value_below_the_floor_and_does_not_write():
    """A request_delay_seconds of 0 would DoS Metacritic — this must be unreachable."""
    row = _row("scraper.request_delay_seconds", "1.5", "float", 0.5, 30)
    session = _session_returning(row)
    config = RuntimeConfig(session)

    with pytest.raises(ValueOutOfRangeError):
        await config.set("scraper.request_delay_seconds", "0", updated_by="op")

    assert row.value == "1.5"  # untouched


async def test_set_rejects_an_unknown_key():
    session = _session_returning(None)
    config = RuntimeConfig(session)

    with pytest.raises(UnknownConfigKeyError):
        await config.set("llm.api_key", "sk-something", updated_by="op")


async def test_set_persists_a_valid_change_and_records_who_made_it():
    row = _row("ingest.games_per_run", "20", "int", 1, 100)
    session = _session_returning(row)
    config = RuntimeConfig(session)

    await config.set("ingest.games_per_run", "5", updated_by="op")

    assert row.value == "5"
    assert row.updated_by == "op"


async def test_set_rejects_a_non_numeric_value_for_an_int_key_instead_of_crashing():
    """Regression: float("garbage") raised a bare, uncaught ValueError before —
    a malformed request would 500 instead of reporting a clean field error."""
    row = _row("ingest.games_per_run", "20", "int", 1, 100)
    session = _session_returning(row)
    config = RuntimeConfig(session)

    with pytest.raises(InvalidValueError):
        await config.set("ingest.games_per_run", "garbage", updated_by="op")

    assert row.value == "20"  # untouched


async def test_set_rejects_a_non_boolean_value_for_a_bool_key():
    row = _row("ingest.enabled", "true", "bool")
    session = _session_returning(row)
    config = RuntimeConfig(session)

    with pytest.raises(InvalidValueError):
        await config.set("ingest.enabled", "maybe", updated_by="op")

    assert row.value == "true"


async def test_set_accepts_false_for_a_bool_key():
    row = _row("ingest.enabled", "true", "bool")
    session = _session_returning(row)
    config = RuntimeConfig(session)

    await config.set("ingest.enabled", "false", updated_by="op")

    assert row.value == "false"


async def test_set_rejects_a_malformed_time_value():
    row = _row("ingest.active_hours_start", "00:00", "time")
    session = _session_returning(row)
    config = RuntimeConfig(session)

    with pytest.raises(InvalidValueError):
        await config.set("ingest.active_hours_start", "not-a-time", updated_by="op")

    assert row.value == "00:00"


async def test_set_accepts_the_24_00_end_of_day_time_value():
    """24:00 is the documented "end of day" sentinel (data-model.md) — not a
    valid stdlib time, but must not be rejected as malformed."""
    row = _row("ingest.active_hours_end", "23:00", "time")
    session = _session_returning(row)
    config = RuntimeConfig(session)

    await config.set("ingest.active_hours_end", "24:00", updated_by="op")

    assert row.value == "24:00"


async def test_list_all_returns_every_seeded_key_for_the_settings_page():
    rows = [_row("ingest.enabled", "true", "bool"), _row("ingest.games_per_run", "20", "int", 1, 100)]
    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    session.execute.return_value = result
    config = RuntimeConfig(session)

    listed = await config.list_all()

    assert listed == rows


async def test_values_are_re_read_per_call_not_cached():
    row = _row("ingest.games_per_run", "20", "int", 1, 100)
    session = _session_returning(row)
    config = RuntimeConfig(session)

    await config.get_int("ingest.games_per_run")
    row.value = "7"
    assert await config.get_int("ingest.games_per_run") == 7
