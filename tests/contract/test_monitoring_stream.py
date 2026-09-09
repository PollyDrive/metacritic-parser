from __future__ import annotations

from metacritic_game_tracker.infrastructure.web.routes_monitoring import (
    _resolve_poll_interval,
    _stage_events,
)


def test_a_fresh_connection_emits_every_known_stage_immediately():
    """Regression: an earlier version only emitted on a *change*, so a visitor
    opening /monitoring mid-run saw nothing until the next transition."""
    latest = {"ingest": (5, "running", "ingest"), "review_refresh": (2, "completed", "review_refresh")}

    lines, updated = _stage_events(latest, last_seen_by_stage={})

    assert len(lines) == 2
    assert any('"stage": "ingest"' in line and '"status": "running"' in line for line in lines)
    assert any('"stage": "review_refresh"' in line and '"status": "completed"' in line for line in lines)
    assert updated == latest


def test_no_event_when_nothing_changed():
    state = {"ingest": (5, "running", "ingest")}

    lines, updated = _stage_events(state, last_seen_by_stage=state)

    assert lines == []
    assert updated == state


def test_only_the_changed_stage_is_emitted_others_stay_quiet():
    """Three independent pipelines — a transition in one must not resend the
    other two, and must not lose their last-known state either."""
    last_seen = {
        "ingest": (5, "running", "ingest"),
        "playthrough": (9, "completed", "playthrough"),
    }
    latest = {
        "ingest": (5, "completed", "ingest"),  # changed
        "playthrough": (9, "completed", "playthrough"),  # unchanged
    }

    lines, updated = _stage_events(latest, last_seen_by_stage=last_seen)

    assert len(lines) == 1
    assert '"stage": "ingest"' in lines[0]
    assert '"status": "completed"' in lines[0]
    assert updated["playthrough"] == (9, "completed", "playthrough")
    assert updated["ingest"] == (5, "completed", "ingest")


def test_resolve_poll_interval_defaults_when_missing():
    assert _resolve_poll_interval(None) == 5


def test_resolve_poll_interval_accepts_an_allowed_value():
    assert _resolve_poll_interval("30") == 30
    assert _resolve_poll_interval("60") == 60
    assert _resolve_poll_interval("300") == 300


def test_resolve_poll_interval_falls_back_on_a_disallowed_value():
    """The client only offers 5/30/60/300 — anything else (tampered, garbage,
    a future value the UI doesn't know yet) falls back to the safe default
    rather than letting an arbitrary interval reach asyncio.sleep."""
    assert _resolve_poll_interval("1") == 5
    assert _resolve_poll_interval("999999") == 5
    assert _resolve_poll_interval("not-a-number") == 5
