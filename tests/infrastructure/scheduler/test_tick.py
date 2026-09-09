from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from metacritic_game_tracker.infrastructure.scheduler.tick import decide


def _config(enabled=True, runs_per_hour=1, start="00:00", end="24:00", tz="UTC"):
    values = {
        "ingest.enabled": enabled,
        "ingest.runs_per_hour": runs_per_hour,
        "ingest.active_hours_start": start,
        "ingest.active_hours_end": end,
        "ingest.timezone": tz,
    }
    config = MagicMock()
    config.get_bool = AsyncMock(side_effect=lambda k: values[k])
    config.get_int = AsyncMock(side_effect=lambda k: values[k])
    config.get_str = AsyncMock(side_effect=lambda k: values[k])
    return config


def _session(pending_request=None, last_finished_at=None):
    session = AsyncMock()

    pending_result = MagicMock()
    pending_result.scalar_one_or_none.return_value = pending_request

    last_run_result = MagicMock()
    last_run_result.scalar_one_or_none.return_value = last_finished_at

    session.execute = AsyncMock(side_effect=[pending_result, last_run_result])
    return session


async def test_pending_run_request_runs_regardless_of_active_hours_and_enabled_flag():
    session = _session(pending_request=42)
    config = _config(enabled=False, start="09:00", end="10:00")  # disabled AND outside hours

    decision = await decide(session, config, now=datetime(2026, 1, 1, 3, 0, tzinfo=UTC))

    assert decision.should_run is True
    assert decision.reason == "manual"
    assert decision.run_request_id == 42


async def test_disabled_master_switch_blocks_a_scheduled_run():
    session = _session(pending_request=None)
    config = _config(enabled=False)

    decision = await decide(session, config, now=datetime(2026, 1, 1, 12, 0, tzinfo=UTC))

    assert decision.should_run is False
    assert decision.reason == "disabled"


async def test_outside_active_hours_blocks_a_scheduled_run():
    session = _session(pending_request=None)
    config = _config(enabled=True, start="09:00", end="17:00")

    decision = await decide(session, config, now=datetime(2026, 1, 1, 3, 0, tzinfo=UTC))

    assert decision.should_run is False
    assert decision.reason == "outside_hours"


async def test_due_when_no_prior_run_exists():
    session = _session(pending_request=None, last_finished_at=None)
    config = _config()

    decision = await decide(session, config, now=datetime(2026, 1, 1, 12, 0, tzinfo=UTC))

    assert decision.should_run is True
    assert decision.reason == "scheduled"


async def test_not_due_yet_within_the_hourly_interval():
    last_run = datetime(2026, 1, 1, 11, 30, tzinfo=UTC)
    session = _session(pending_request=None, last_finished_at=last_run)
    config = _config(runs_per_hour=1)

    decision = await decide(session, config, now=datetime(2026, 1, 1, 12, 0, tzinfo=UTC))

    assert decision.should_run is False
    assert decision.reason == "not_due_yet"


async def test_a_restart_does_not_reset_the_schedule():
    """Due-ness comes from pipeline_runs in the DB, not an in-memory timer
    (research.md §3) — a fresh process instance sees the same last-run time."""
    last_run = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
    session = _session(pending_request=None, last_finished_at=last_run)
    config = _config(runs_per_hour=1)

    decision = await decide(session, config, now=datetime(2026, 1, 1, 12, 0, tzinfo=UTC))

    assert decision.should_run is True
    assert decision.reason == "scheduled"
