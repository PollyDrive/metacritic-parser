from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class IngestState:
    current_day: date
    day_processed_count: int
    see_all_next_page: int


@dataclass(frozen=True)
class NewReleasesSource:
    pass


@dataclass(frozen=True)
class SeeAllSource:
    page: int


Source = NewReleasesSource | SeeAllSource


def day_key(now: datetime, timezone_name: str) -> date:
    """Resolve the calendar day `now` falls on in `timezone_name` (FR-005, research.md §12)."""
    return now.astimezone(ZoneInfo(timezone_name)).date()


def roll_over_if_new_day(state: IngestState, today: date) -> IngestState:
    """Reset per-day progress at the start of a new calendar day (FR-005)."""
    if state.current_day == today:
        return state
    return IngestState(current_day=today, day_processed_count=0, see_all_next_page=1)


def advance_state(state: IngestState, used_fallback: bool, processed_count: int) -> IngestState:
    """FR-002/003 (revised): every run tries New Releases first and falls back to
    See All (at the stored forward-only cursor) only when New Releases had zero
    games not already in the catalog. The cursor advances only on a run that
    actually used the fallback."""
    see_all_next_page = state.see_all_next_page + 1 if used_fallback else state.see_all_next_page
    return replace(
        state,
        day_processed_count=state.day_processed_count + processed_count,
        see_all_next_page=see_all_next_page,
    )


def normalize_genres(raw_genres: list[str]) -> list[str]:
    """Dedupe (case-insensitively, first-seen casing wins) and trim genre names extracted
    from the SSR payload, for the similar-games genre-overlap query (research.md §4) —
    never loads or touches the catalog."""
    seen: set[str] = set()
    result: list[str] = []
    for raw in raw_genres:
        cleaned = raw.strip()
        key = cleaned.lower()
        if not cleaned or key in seen:
            continue
        seen.add(key)
        result.append(cleaned)
    return result


def calculate_next_refresh(
    release_date: date | None,
    current_time: datetime,
    recent_tier_days: int = 3,
    mid_tier_days: int = 7,
    max_age_weeks: int = 4,
) -> datetime | None:
    """Implement Decayed TTL review refresh based on game age.
    - Age < 7 days: refresh every `recent_tier_days` (FR-010: operator-tunable).
    - Age 7 days to `max_age_weeks` weeks: refresh every `mid_tier_days`.
    - Older, or missing release_date: never refresh.

    The 7-day boundary between the two tiers is fixed (spec.md's own bucket
    definition); only the recheck cadence within each tier and the outer
    cutoff age are configurable.
    """
    if not release_date:
        return None
    age = (current_time.date() - release_date).days
    if age < 7:
        return current_time + timedelta(days=recent_tier_days)
    if age <= max_age_weeks * 7:
        return current_time + timedelta(days=mid_tier_days)
    return None


def calculate_llm_cost(
    input_tokens: int, output_tokens: int, input_cost_per_1m: Decimal, output_cost_per_1m: Decimal
) -> Decimal:
    """Cost of one LLM call from per-million-token rates (meta.llm_model_costs)."""
    million = Decimal(1_000_000)
    return (Decimal(input_tokens) / million) * Decimal(input_cost_per_1m) + (
        Decimal(output_tokens) / million
    ) * Decimal(output_cost_per_1m)
