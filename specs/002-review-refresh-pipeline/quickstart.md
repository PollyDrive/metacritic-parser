# Quickstart: Review Refresh Pipeline

Validation guide — proves the feature works end-to-end once implemented. Not a spec of
behavior (see `spec.md`) or of internals (see `data-model.md` / `research.md`). Builds on the
sibling feature's own quickstart (`specs/001-metacritic-game-tracker/quickstart.md`) — start
there for infrastructure/migrations/running the two processes; this guide only covers what's
new.

**Verified against a running instance on 2026-09-10** (migrations applied through
`012_review_refresh_decay_config.sql`, `app`+`worker` rebuilt and restarted) — steps below
reflect what was actually confirmed live, not just read from code. Field/config names below
were corrected from the original draft (`reviews_last_checked_at`, `review_count_at_generation`,
`review_refresh.growth_threshold_pct`) to match what's actually built — see data-model.md's and
research.md's own "Revised during implementation" notes.

## Prerequisites

- Sibling feature's quickstart steps 1-3 done: infrastructure up, migrations applied
  (including this feature's `sql/migrations/010`-`012_*.sql`), `app` + `worker` running.
- At least one game already cataloged with both review summaries generated (run the existing
  ingestion quickstart, or seed directly).

## 1. Confirm the initial pipeline records counts

1. Trigger or wait for a normal ingest run to catalog a new game (sibling quickstart §4/§8).
2. Inspect that game's `review_summaries` rows (both audiences): `total_reviews_count` must be
   populated (not null, not zero unless that audience genuinely had zero reviews at generation
   time) — confirmed live via `application/ingest.py`'s inline enrichment call writing this
   column at first creation.

**Pass condition**: matches spec.md User Story 1, Acceptance Scenario 3.

## 2. Confirm a recheck without meaningful growth leaves the summary alone

1. Pick a cataloged game whose `review_summaries.total_reviews_count` is close to its actual
   current Metacritic review count (freshly ingested games qualify).
2. Wait for (or manually trigger via `POST /monitoring/run?kind=review_refresh`) a refresh pass
   covering that game.
3. Confirm in `pipeline_runs` a row with `stage = 'review_refresh'` appears for that run.
4. Confirm the game's `games.next_refresh_at` advanced, but its `review_summaries` rows
   (`summary_text`, `total_reviews_count`, `generated_at`) are unchanged, and no new `llm_calls`
   row was written for this game.

**Pass condition**: matches spec.md User Story 2, Acceptance Scenarios 2-3.

## 3. Confirm a recheck with significant growth regenerates the summary

1. Pick (or seed) a cataloged game and set its `review_summaries.total_reviews_count` for one
   audience well below that audience's actual current Metacritic review count on its winning
   platform — enough to clear `reviews.growth_threshold` (default `10`, a flat count, not a
   percentage; see `/monitoring/config`).
2. Also set `games.next_refresh_at` to `NULL` or far enough in the past to be due under
   `review_refresh.recent_tier_days` / `mid_tier_days` for that game's age.
3. Wait for (or manually trigger) a refresh pass.
4. Confirm that audience's `review_summaries` row changed: new `summary_text`, new
   `total_reviews_count` matching the freshly observed count, updated `generated_at`, populated
   `source_platform`/`source_url`, and a new `llm_calls` row recorded against it (with `cost_usd`
   populated, not zero).
5. Confirm the *other* audience, if its growth stayed under threshold, was left untouched.

**Pass condition**: matches spec.md User Story 1, Acceptance Scenarios 1-2.

## 4. Confirm the decay curve and cutoff

1. Seed three games at different ages relative to `first_seen_at`: under 1 week, between 1 and
   4 weeks, and past `review_refresh.max_age_weeks` (default 4 weeks).
2. Run several refresh passes over simulated time (or inspect the due-selection query directly
   against seeded `next_refresh_at` values).
3. Confirm the under-1-week game is selected roughly every `recent_tier_days` (default 3), the
   1-4-week game roughly every `mid_tier_days` (default 7), and the past-cutoff game is never
   selected regardless of how long it's been since its last check.

**Pass condition**: matches spec.md User Story 2, Acceptance Scenario 1; spec.md SC-003.

## 5. Confirm the pass is capped and prioritizes younger games

**Live-verified 2026-09-10**: before this feature's Foundational fix, a manually-triggered
`review_refresh` run processed 387 games in one tick (`pipeline_runs.items_in`) — every due
game, unbounded. After the fix, an equivalent trigger processed exactly 40
(`review_refresh.games_per_run=20` × 2 audiences), and the games actually selected were the
highest-id (most-recently-`first_seen_at`) ones in the catalog, confirming both the cap and the
youngest-first ordering (`application/backfill.py`'s `_games_missing`).

1. Trigger a manual `review_refresh` run while more than `review_refresh.games_per_run` games
   are due.
2. Confirm `pipeline_runs.items_in` for that run equals `games_per_run × 2` (critic + user), not
   the full due count.
3. Confirm the games touched (via `game_activity_events` for ones that regenerated, or by
   `games.next_refresh_at` for ones that didn't) are the youngest by `first_seen_at` among the
   due set.

**Pass condition**: matches spec.md FR-012, SC-003.

## 6. Confirm the refresh pass never blocks new-game discovery

1. While a refresh pass has games queued (e.g. many games due at once), trigger a manual
   ingest run (`/monitoring` → Run now, per the sibling feature's operator console).
2. Confirm the ingest run's `pipeline_runs` row completes in line with its usual duration —
   unaffected by how many games were due for a refresh recheck in the same tick. Structurally
   guaranteed: `infrastructure/scheduler/tick.py`'s `decide()` (ingest's due-check) and
   `stage_due()` (review_refresh's/playthrough's) each filter `pipeline_runs` by their own
   `stage` only, never reading each other's rows.

**Pass condition**: matches spec.md SC-004.

## 7. Full quality gate (Constitution Principle IV)

```bash
poetry run ruff check .
poetry run tach check
poetry run pytest tests/ -q
```

All three must be clean before the feature is considered done.

**Note**: while live-testing this quickstart, ingest runs in the running instance repeatedly hit
a pre-existing, unrelated crash (`sqlalchemy.exc.MissingGreenlet` in
`GameRepository.upsert_platform_scores`) — not introduced by this feature, flagged separately for
a dedicated fix.
