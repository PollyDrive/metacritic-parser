from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class IngestState:
    current_day: date
    day_processed_count: int
    day_new_releases_done: bool
    see_all_next_page: int


@dataclass(frozen=True)
class NewReleasesSource:
    pass


@dataclass(frozen=True)
class SeeAllSource:
    page: int


Source = NewReleasesSource | SeeAllSource


@dataclass(frozen=True)
class IngestPlan:
    primary: Source
    topup: SeeAllSource | None


def day_key(now: datetime, timezone_name: str) -> date:
    """Resolve the calendar day `now` falls on in `timezone_name` (FR-005, research.md §12)."""
    return now.astimezone(ZoneInfo(timezone_name)).date()


def roll_over_if_new_day(state: IngestState, today: date) -> IngestState:
    """Reset per-day progress at the start of a new calendar day (FR-005)."""
    if state.current_day == today:
        return state
    return IngestState(
        current_day=today,
        day_processed_count=0,
        day_new_releases_done=False,
        see_all_next_page=1,
    )


def plan_ingest(state: IngestState) -> IngestPlan:
    """FR-002/003: New Releases on the first run of the day, See All (at the stored
    cursor) afterward. A top-up source is always prepared alongside New Releases so
    the orchestrator can use it immediately if New Releases comes up short (FR-005).

    On every subsequent run, topup is ALWAYS See All's page 1 — not just on
    shortfall. See All's own cursor only moves forward and never revisits page
    1, but the listing itself drifts (new games are added to page 1 all day),
    so without this, anything published after the day's first run would be
    permanently missed once the cursor has advanced past page 1."""
    if not state.day_new_releases_done:
        return IngestPlan(
            primary=NewReleasesSource(),
            topup=SeeAllSource(page=state.see_all_next_page),
        )
    return IngestPlan(primary=SeeAllSource(page=state.see_all_next_page), topup=SeeAllSource(page=1))


def advance_state(
    state: IngestState,
    plan: IngestPlan,
    primary_count: int,
    topup_used: bool,
    topup_count: int,
) -> IngestState:
    """Update cursor/day progress after a completed (non-aborted) run."""
    day_new_releases_done = state.day_new_releases_done or isinstance(plan.primary, NewReleasesSource)
    see_all_next_page = state.see_all_next_page
    if isinstance(plan.primary, SeeAllSource):
        see_all_next_page += 1
    if topup_used and isinstance(plan.primary, NewReleasesSource):
        # Day-start's shortfall topup consumes page 1 as the day's first See
        # All page, so it advances the cursor like any other See All primary
        # run. A later run's always-on drift-correction topup re-checks page
        # 1 every single time and must NOT advance the cursor — it isn't a
        # continuation of the long-tail traversal, it's a fixed recheck.
        see_all_next_page += 1
    return replace(
        state,
        day_processed_count=state.day_processed_count + primary_count + topup_count,
        day_new_releases_done=day_new_releases_done,
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
