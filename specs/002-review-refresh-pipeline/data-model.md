# Phase 1 Data Model: Review Refresh Pipeline

Extends the existing `games` and `review_summaries` tables (`sql/migrations/003_games.sql`)
and the existing `runtime_config` mechanism (`sql/migrations/005_runtime_config.sql`) rather
than introducing new tables — see research.md §2/§3 for why the spec's two Key Entities map
onto columns on tables that already exist instead of new ones.

## `games` (extended)

One new nullable column.

| Field | Type | Notes |
|---|---|---|
| `reviews_last_checked_at` | timestamptz, nullable, default `NULL` | Set by the refresh pass every time it recheck-visits this game (whether or not that visit triggered a regeneration). `NULL` means "never visited by the refresh pass" and is always due (research.md §3). Age for decay-curve bucketing is measured from the existing `first_seen_at`, not from this column. |

## `review_summaries` (extended)

One new required column.

| Field | Type | Notes |
|---|---|---|
| `review_count_at_generation` | integer, not null | The review count for this row's audience at the moment this summary was (re)generated. Written by whichever pipeline generates the row — the initial-ingest pipeline on first creation, the refresh pass on every regeneration. The refresh pass's growth check compares a freshly observed count against this value (research.md §4). |

**Validation**: `review_count_at_generation >= 0`. Never written independently of the
`summary_text` it accompanies — both are set together, by the same insert/update.

## RuntimeConfig (new seeded keys)

Same table and mechanism as the sibling feature's `runtime_config` (data-model.md §RuntimeConfig
there) — operator-tunable, server-side-bounded, re-read per run. New keys, seeded by this
feature's migration:

| Key | Default | Bounds | Meaning |
|---|---|---|---|
| `review_refresh.enabled` | `true` | — | master switch for the refresh pass |
| `review_refresh.games_per_run` | `20` | 1-200 | cap on games recheck-visited per worker tick (research.md §5) |
| `review_refresh.recent_tier_days` | `3` | 1-30 | recheck interval for games younger than 1 week |
| `review_refresh.mid_tier_days` | `7` | 1-90 | recheck interval for games 1-4 weeks old |
| `review_refresh.max_age_weeks` | `4` | 1-52 | age past which a game is excluded from the refresh pass entirely |
| `review_refresh.growth_threshold_pct` | `0.25` | 0.01-5.0 | fraction of the recorded count a game's observed count must exceed it by to trigger regeneration (research.md §4) |

**Validation**: identical bounds-checking mechanism as every other `runtime_config` key
(`infrastructure/config/runtime.py`, already built) — writes out of bounds are rejected
server-side, not just in the browser.

## Relationships

```text
Game 1──0..2 ReviewSummary   (audience='critic' | 'user', now carries review_count_at_generation)
Game.reviews_last_checked_at + Game.first_seen_at ──(decay-curve due-check)──> refresh pass's candidate set
```

## State Transitions

The refresh pass does not introduce a new status column — like the rest of this project's
enrichment (spec 001 data-model.md's own State Transitions section), completion is derived by
comparing two values, not tracked as an explicit state:

```text
due game (age < max_age_weeks, reviews_last_checked_at stale for its age bracket)
├── observed count (per audience) clears growth threshold over review_count_at_generation
│     → summary regenerated, review_count_at_generation updated, reviews_last_checked_at updated
└── observed count does not clear threshold
      → reviews_last_checked_at updated, summary and review_count_at_generation untouched
```

A regeneration failure (e.g. LLM call fails) leaves `review_count_at_generation` and
`reviews_last_checked_at` at their prior values for that audience specifically — the next time
this game becomes due again on its normal cadence, the same (now larger) observed-vs-recorded
gap will re-attempt it. No separate retry/backoff table: the decay curve's own interval is the
backoff, consistent with how `application/ingest.py`'s inline enrichment already treats a
summarization failure as non-fatal and self-healing on a later pass rather than tracked as a
distinct failure state.
