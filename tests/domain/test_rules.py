from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from metacritic_game_tracker.domain.rules import (
    IngestState,
    advance_state,
    calculate_llm_cost,
    calculate_next_refresh,
    day_key,
    roll_over_if_new_day,
)


def test_day_key_resolves_calendar_day_in_configured_timezone():
    # 2026-01-01 23:30 UTC is already 2026-01-02 in UTC+1
    now = datetime(2026, 1, 1, 23, 30, tzinfo=UTC)
    assert day_key(now, "UTC") == date(2026, 1, 1)
    assert day_key(now, "Europe/Warsaw") == date(2026, 1, 2)


def test_roll_over_if_new_day_resets_state_when_day_changes():
    state = IngestState(current_day=date(2026, 1, 1), day_processed_count=15, see_all_next_page=4)
    rolled = roll_over_if_new_day(state, date(2026, 1, 2))
    assert rolled == IngestState(current_day=date(2026, 1, 2), day_processed_count=0, see_all_next_page=1)


def test_roll_over_if_new_day_is_noop_within_same_day():
    state = IngestState(current_day=date(2026, 1, 1), day_processed_count=15, see_all_next_page=4)
    assert roll_over_if_new_day(state, date(2026, 1, 1)) is state


def test_advance_state_leaves_cursor_untouched_when_new_releases_covered_the_run():
    """FR-002/003: New Releases had candidates this run -> See All wasn't touched,
    so its cursor must not move."""
    state = IngestState(current_day=date(2026, 1, 1), day_processed_count=0, see_all_next_page=3)
    new_state = advance_state(state, used_fallback=False, processed_count=20)
    assert new_state.see_all_next_page == 3
    assert new_state.day_processed_count == 20


def test_advance_state_advances_cursor_by_one_page_when_fallback_was_used():
    """FR-003: a run that fell back to See All (New Releases had nothing new)
    moves that source's forward-only cursor to the next page."""
    state = IngestState(current_day=date(2026, 1, 1), day_processed_count=20, see_all_next_page=3)
    new_state = advance_state(state, used_fallback=True, processed_count=20)
    assert new_state.see_all_next_page == 4
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
