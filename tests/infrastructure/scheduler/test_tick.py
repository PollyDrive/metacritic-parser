from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from metacritic_game_tracker.infrastructure.scheduler.tick import decide, dispatch_due, stage_due


def _config(enabled=True):
    values = {"ingest.enabled": enabled}
    config = MagicMock()
    config.get_bool = AsyncMock(side_effect=lambda k: values[k])
    return config


def _session(pending_request=None, last_finished_at=None):
    session = AsyncMock()

    pending_result = MagicMock()
    pending_result.scalar_one_or_none.return_value = pending_request

    last_run_result = MagicMock()
    last_run_result.scalar_one_or_none.return_value = last_finished_at

    session.execute = AsyncMock(side_effect=[pending_result, last_run_result])
    return session


async def test_pending_run_request_runs_regardless_of_the_enabled_flag():
    session = _session(pending_request=42)
    config = _config(enabled=False)

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


async def test_due_when_no_prior_run_exists():
    session = _session(pending_request=None, last_finished_at=None)
    config = _config()

    decision = await decide(session, config, now=datetime(2026, 1, 1, 12, 0, tzinfo=UTC))

    assert decision.should_run is True
    assert decision.reason == "scheduled"


async def test_not_due_yet_within_the_hourly_interval():
    last_run = datetime(2026, 1, 1, 11, 30, tzinfo=UTC)
    session = _session(pending_request=None, last_finished_at=last_run)
    config = _config()

    decision = await decide(session, config, now=datetime(2026, 1, 1, 12, 0, tzinfo=UTC))

    assert decision.should_run is False
    assert decision.reason == "not_due_yet"


async def test_a_restart_does_not_reset_the_schedule():
    """Due-ness comes from pipeline_runs in the DB, not an in-memory timer
    (research.md §3) — a fresh process instance sees the same last-run time."""
    last_run = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
    session = _session(pending_request=None, last_finished_at=last_run)
    config = _config()

    decision = await decide(session, config, now=datetime(2026, 1, 1, 12, 0, tzinfo=UTC))

    assert decision.should_run is True
    assert decision.reason == "scheduled"


def _stage_session(last_finished_at):
    session = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = last_finished_at
    session.execute = AsyncMock(return_value=result)
    return session


async def test_decides_ingest_due_ness_from_ingest_stage_runs_only():
    """FR-003/SC-004: a manual or scheduled ingest run's timing must be
    unaffected by how many games are queued for review_refresh in the same
    tick — decide()'s own due-check is scoped strictly to stage='ingest',
    never touching review_refresh's or playthrough's pipeline_runs rows."""
    session = _session(pending_request=None, last_finished_at=None)

    await decide(session, _config(), now=datetime(2026, 1, 1, 12, 0, tzinfo=UTC))

    last_run_stmt = session.execute.call_args_list[1].args[0]
    compiled = str(last_run_stmt.compile(compile_kwargs={"literal_binds": True})).lower()
    assert "stage = 'ingest'" in compiled


def test_dispatch_due_a_manual_trigger_proceeds_even_when_disabled_and_not_due():
    """FR-009: an operator-initiated run of a specific pipeline proceeds
    regardless of that pipeline's own enable setting."""
    assert dispatch_due("playthrough", "playthrough", enabled=False, due=False) is True


def test_dispatch_due_a_scheduled_tick_needs_both_enabled_and_due():
    assert dispatch_due("scheduled", "review_refresh", enabled=True, due=True) is True
    assert dispatch_due("scheduled", "review_refresh", enabled=False, due=True) is False
    assert dispatch_due("scheduled", "review_refresh", enabled=True, due=False) is False
    assert dispatch_due("scheduled", "review_refresh", enabled=False, due=False) is False


def test_dispatch_due_a_manual_trigger_for_a_different_stage_does_not_fire():
    assert dispatch_due("playthrough", "review_refresh", enabled=True, due=True) is False


def test_dispatch_due_for_review_refresh_and_playthrough_never_depends_on_ingest():
    """FR-002/FR-006/FR-007: discovery being off must never affect these two
    other pipelines — dispatch_due takes each stage's own enabled/due state
    as parameters, with no ingest-related input at all, so this holds by
    construction rather than by incidental behavior."""
    assert dispatch_due("scheduled", "review_refresh", enabled=True, due=True) is True
    assert dispatch_due("scheduled", "playthrough", enabled=True, due=True) is True


async def test_stage_due_when_the_stage_has_never_completed_a_run():
    session = _stage_session(last_finished_at=None)

    assert await stage_due(session, "playthrough", 3, now=datetime(2026, 1, 1, 12, 0, tzinfo=UTC)) is True


async def test_stage_not_due_within_its_own_interval():
    last_run = datetime(2026, 1, 1, 11, 0, tzinfo=UTC)
    session = _stage_session(last_finished_at=last_run)

    due = await stage_due(session, "review_refresh", 3, now=datetime(2026, 1, 1, 12, 0, tzinfo=UTC))

    assert due is False


async def test_stage_due_once_its_own_interval_has_elapsed():
    last_run = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)
    session = _stage_session(last_finished_at=last_run)

    due = await stage_due(session, "playthrough", 3, now=datetime(2026, 1, 1, 12, 0, tzinfo=UTC))

    assert due is True
