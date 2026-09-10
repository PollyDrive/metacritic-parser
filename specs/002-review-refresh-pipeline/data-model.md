# Phase 1 Data Model: Review Refresh Pipeline

Extends the existing `games` and `review_summaries` tables (`sql/migrations/003_games.sql`)
and the existing `runtime_config` mechanism (`sql/migrations/005_runtime_config.sql`) rather
than introducing new tables — see research.md §2/§3 for why the spec's two Key Entities map
onto columns on tables that already exist instead of new ones.

## `games` (extended)

[Revised during implementation: `reviews_last_checked_at` was never added as a separate
column — `games.next_refresh_at` (`sql/migrations/005_release_date_and_refresh.sql`, shared
with spec 001's Decayed TTL) does double duty as both "when is this game next due" and, by
its presence/absence, "has the refresh pass ever visited this game." A `NULL` value means
never visited and is always due; `domain/rules.py`'s `calculate_next_refresh` computes the
next value from `first_seen_at`-based age on every visit, whether or not that visit
triggered a regeneration (research.md §3).]

| Field | Type | Notes |
|---|---|---|
| `next_refresh_at` | timestamptz, nullable | Set by `application/enrichment.py`'s `ReviewEnrichmentUseCase.run()` on every recheck-visit — both when growth clears the threshold and when it doesn't. `NULL` means "never visited" and is always due. Age for decay-curve bucketing is measured from the existing `first_seen_at`, not from this column. |

## `review_summaries` (extended)

[Revised during implementation: the column is `total_reviews_count`, not
`review_count_at_generation` — added alongside `sampled_reviews_count`, `source_url`, and
`source_platform` by `sql/migrations/011_review_count_and_threshold.sql`, since a summary's
provenance (which platform it was sampled from, how many of that platform's reviews were fed
to the LLM, a link back to the source) turned out to matter as much as the raw count.]

| Field | Type | Notes |
|---|---|---|
| `total_reviews_count` | integer, not null default `0` | The winning platform's total review count for this row's audience at the moment this summary was (re)generated. Written by whichever pipeline generates the row — the initial-ingest pipeline on first creation, the refresh pass on every regeneration. The refresh pass's growth check compares a freshly observed count against this value (research.md §1, §4). |
| `sampled_reviews_count` | integer, not null default `0` | How many of that platform's reviews were actually fed to the LLM (bounded by `reviews.critic_sample_size`/`user_sample_size`) — distinct from `total_reviews_count`, which is the platform's real total. |
| `source_url` | text, nullable | Link back to the Metacritic reviews page the sample was drawn from, platform-scoped when known. |
| `source_platform` | text, nullable | The platform `pick_best_platform` selected for this generation; `NULL` only on the SSR-fallback path, where no reliable per-platform attribution exists. |

**Validation**: `total_reviews_count >= 0`. Never written independently of the `summary_text`
it accompanies — both are set together, by the same insert/update.

## RuntimeConfig (new seeded keys)

Same table and mechanism as the sibling feature's `runtime_config` (data-model.md §RuntimeConfig
there) — operator-tunable, server-side-bounded, re-read per run.

| Key | Default | Bounds | Meaning |
|---|---|---|---|
| `review_refresh.games_per_run` | `20` | 1-200 | cap on games recheck-visited per worker tick, youngest-due first (FR-012, research.md §5) |
| `review_refresh.recent_tier_days` | `3` | 1-30 | recheck interval for games younger than 1 week |
| `review_refresh.mid_tier_days` | `7` | 1-90 | recheck interval for games 1-4 weeks old |
| `review_refresh.max_age_weeks` | `4` | 1-52 | age past which a game is excluded from the refresh pass entirely |
| `reviews.growth_threshold` | `10` | 1-1000 | [Revised during implementation: a flat review-count delta, not `review_refresh.growth_threshold_pct`'s originally-planned fraction — the winning platform's review count must grow by at least this many since the summary on file to trigger regeneration (research.md §1, §4).] |

**Validation**: identical bounds-checking mechanism as every other `runtime_config` key
(`infrastructure/config/runtime.py`, already built) — writes out of bounds are rejected
server-side, not just in the browser.

Cadence note: the review-refresh *pass itself* (as opposed to the per-game decay curve above)
runs on its own worker-tick cadence, `review_refresh.interval_hours` (seeded by
`sql/migrations/010_review_playthrough_cadence_and_sample_size.sql`, default 3) — decoupled
from ingest's hourly tick, since most hourly ticks would otherwise find nothing due.

## Relationships

```text
Game 1──0..2 ReviewSummary   (audience='critic' | 'user', now carries total_reviews_count/
                              sampled_reviews_count/source_url/source_platform)
Game.next_refresh_at + Game.first_seen_at ──(decay-curve due-check)──> refresh pass's candidate set
```

## State Transitions

The refresh pass does not introduce a new status column — like the rest of this project's
enrichment (spec 001 data-model.md's own State Transitions section), completion is derived by
comparing two values, not tracked as an explicit state:

```text
due game (age < max_age_weeks, next_refresh_at stale/NULL for its age bracket)
├── observed count (per audience, winning platform) clears growth threshold over total_reviews_count
│     → summary regenerated, total_reviews_count updated, next_refresh_at advanced
└── observed count does not clear threshold
      → next_refresh_at advanced, summary and total_reviews_count untouched
```

A regeneration failure (e.g. LLM call fails) leaves `total_reviews_count` and `next_refresh_at`
at their prior values for that audience specifically — the next time this game becomes due
again on its normal cadence, the same (now larger) observed-vs-recorded gap will re-attempt it.
No separate retry/backoff table: the decay curve's own interval is the backoff, consistent with
how `application/ingest.py`'s inline enrichment already treats a summarization failure as
non-fatal and self-healing on a later pass rather than tracked as a distinct failure state.
