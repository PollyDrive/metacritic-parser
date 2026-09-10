from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from metacritic_game_tracker.domain.rules import (
    IngestState,
    NewReleasesSource,
    SeeAllSource,
    advance_state,
    calculate_llm_cost,
    calculate_next_refresh,
    day_key,
    plan_ingest,
    roll_over_if_new_day,
)


def test_day_key_resolves_calendar_day_in_configured_timezone():
    # 2026-01-01 23:30 UTC is already 2026-01-02 in UTC+1
    now = datetime(2026, 1, 1, 23, 30, tzinfo=UTC)
    assert day_key(now, "UTC") == date(2026, 1, 1)
    assert day_key(now, "Europe/Warsaw") == date(2026, 1, 2)


def test_roll_over_if_new_day_resets_state_when_day_changes():
    state = IngestState(
        current_day=date(2026, 1, 1),
        day_processed_count=15,
        day_new_releases_done=True,
        see_all_next_page=4,
    )
    rolled = roll_over_if_new_day(state, date(2026, 1, 2))
    assert rolled == IngestState(
        current_day=date(2026, 1, 2),
        day_processed_count=0,
        day_new_releases_done=False,
        see_all_next_page=1,
    )


def test_roll_over_if_new_day_is_noop_within_same_day():
    state = IngestState(
        current_day=date(2026, 1, 1),
        day_processed_count=15,
        day_new_releases_done=True,
        see_all_next_page=4,
    )
    assert roll_over_if_new_day(state, date(2026, 1, 1)) is state


def test_plan_ingest_uses_new_releases_first_with_a_topup_ready():
    state = IngestState(
        current_day=date(2026, 1, 1),
        day_processed_count=0,
        day_new_releases_done=False,
        see_all_next_page=1,
    )
    plan = plan_ingest(state)
    assert plan.primary == NewReleasesSource()
    assert plan.topup == SeeAllSource(page=1)


def test_plan_ingest_uses_see_all_at_stored_cursor_once_new_releases_done():
    """Real bug: the cursor only moves forward and never revisits page 1, but
    the listing itself drifts (new games are added to page 1 throughout the
    day) — without an always-on page-1 topup on every subsequent run, games
    published after the day's first run were permanently missed once the
    cursor had advanced past page 1."""
    state = IngestState(
        current_day=date(2026, 1, 1),
        day_processed_count=20,
        day_new_releases_done=True,
        see_all_next_page=3,
    )
    plan = plan_ingest(state)
    assert plan.primary == SeeAllSource(page=3)
    assert plan.topup == SeeAllSource(page=1)


def test_advance_state_marks_new_releases_done_and_leaves_cursor_when_no_topup_needed():
    state = IngestState(
        current_day=date(2026, 1, 1),
        day_processed_count=0,
        day_new_releases_done=False,
        see_all_next_page=1,
    )
    plan = plan_ingest(state)
    new_state = advance_state(state, plan, primary_count=20, topup_used=False, topup_count=0)
    assert new_state.day_new_releases_done is True
    assert new_state.see_all_next_page == 1
    assert new_state.day_processed_count == 20


def test_advance_state_tops_up_from_see_all_and_advances_cursor_by_one_page():
    """FR-005: New Releases short -> top up from See All within same run."""
    state = IngestState(
        current_day=date(2026, 1, 1),
        day_processed_count=0,
        day_new_releases_done=False,
        see_all_next_page=1,
    )
    plan = plan_ingest(state)
    new_state = advance_state(state, plan, primary_count=12, topup_used=True, topup_count=8)
    assert new_state.day_new_releases_done is True
    assert new_state.see_all_next_page == 2
    assert new_state.day_processed_count == 20


def test_advance_state_advances_cursor_on_subsequent_see_all_runs():
    state = IngestState(
        current_day=date(2026, 1, 1),
        day_processed_count=20,
        day_new_releases_done=True,
        see_all_next_page=3,
    )
    plan = plan_ingest(state)
    new_state = advance_state(state, plan, primary_count=20, topup_used=False, topup_count=0)
    assert new_state.see_all_next_page == 4
    assert new_state.day_processed_count == 40


def test_advance_state_does_not_double_advance_when_the_always_on_topup_fires():
    """Real bug regression: a later run's page-1 topup is a fixed recheck,
    not a continuation of the long-tail cursor — using it must advance the
    cursor exactly once (for the SeeAllSource primary), not twice."""
    state = IngestState(
        current_day=date(2026, 1, 1),
        day_processed_count=20,
        day_new_releases_done=True,
        see_all_next_page=3,
    )
    plan = plan_ingest(state)
    new_state = advance_state(state, plan, primary_count=18, topup_used=True, topup_count=2)
    assert new_state.see_all_next_page == 4  # not 5
    assert new_state.day_processed_count == 40


def test_calculate_next_refresh_for_game_under_7_days_old():
    current_time = datetime(2024, 1, 10, 12, 0, 0, tzinfo=UTC)
    # Age is 5 days
    release_date = date(2024, 1, 5)
    next_refresh = calculate_next_refresh(release_date, current_time)
    assert next_refresh == current_time + timedelta(days=3)

def test_calculate_next_refresh_for_game_between_7_and_28_days_old():
    current_time = datetime(2024, 1, 30, 12, 0, 0, tzinfo=UTC)
    # Age is 20 days
    release_date = date(2024, 1, 10)
    next_refresh = calculate_next_refresh(release_date, current_time)
    assert next_refresh == current_time + timedelta(days=7)

def test_calculate_next_refresh_for_game_over_28_days_old():
    current_time = datetime(2024, 3, 10, 12, 0, 0, tzinfo=UTC)
    # Age is > 28 days
    release_date = date(2024, 1, 10)
    next_refresh = calculate_next_refresh(release_date, current_time)
    assert next_refresh is None

def test_calculate_next_refresh_with_no_release_date():
    current_time = datetime(2024, 1, 10, 12, 0, 0, tzinfo=UTC)
    next_refresh = calculate_next_refresh(None, current_time)
    assert next_refresh is None

def test_calculate_next_refresh_honors_a_configured_recent_tier_interval():
    """FR-010: the recheck interval is operator-tunable, not hardcoded."""
    current_time = datetime(2024, 1, 10, 12, 0, 0, tzinfo=UTC)
    release_date = date(2024, 1, 5)  # 5 days old — under the 1-week boundary
    next_refresh = calculate_next_refresh(
        release_date, current_time, recent_tier_days=1, mid_tier_days=7, max_age_weeks=4,
    )
    assert next_refresh == current_time + timedelta(days=1)

def test_calculate_next_refresh_honors_a_configured_mid_tier_interval():
    current_time = datetime(2024, 1, 30, 12, 0, 0, tzinfo=UTC)
    release_date = date(2024, 1, 10)  # 20 days old — 1-4 week bucket
    next_refresh = calculate_next_refresh(
        release_date, current_time, recent_tier_days=3, mid_tier_days=14, max_age_weeks=4,
    )
    assert next_refresh == current_time + timedelta(days=14)

def test_calculate_next_refresh_honors_a_configured_max_age_cutoff():
    """A game that would exit at the default 4-week cutoff keeps refreshing
    under a wider configured cutoff."""
    current_time = datetime(2024, 3, 10, 12, 0, 0, tzinfo=UTC)
    release_date = date(2024, 1, 10)  # ~59 days old — past the default cutoff
    next_refresh = calculate_next_refresh(
        release_date, current_time, recent_tier_days=3, mid_tier_days=7, max_age_weeks=52,
    )
    assert next_refresh == current_time + timedelta(days=7)

def test_calculate_next_refresh_never_reactivates_no_matter_how_much_later():
    """spec.md Edge Cases: a game past the cutoff exits the refresh pass for
    good — not just at the moment it crosses the boundary."""
    release_date = date(2024, 1, 10)
    a_year_later = datetime(2025, 1, 10, 12, 0, 0, tzinfo=UTC)
    assert calculate_next_refresh(release_date, a_year_later) is None

def test_calculate_llm_cost_combines_input_and_output_rates():
    cost = calculate_llm_cost(
        input_tokens=1_000_000, output_tokens=1_000_000,
        input_cost_per_1m=Decimal("0.80"), output_cost_per_1m=Decimal("4.00"),
    )
    assert cost == Decimal("4.80")

def test_calculate_llm_cost_scales_below_one_million_tokens():
    cost = calculate_llm_cost(
        input_tokens=1_000, output_tokens=500,
        input_cost_per_1m=Decimal("3.00"), output_cost_per_1m=Decimal("15.00"),
    )
    assert cost == Decimal("0.0105")

def test_calculate_llm_cost_of_zero_tokens_is_zero():
    cost = calculate_llm_cost(
        input_tokens=0, output_tokens=0,
        input_cost_per_1m=Decimal("3.00"), output_cost_per_1m=Decimal("15.00"),
    )
    assert cost == Decimal("0")
