# Quickstart: Review Refresh Pipeline

Validation guide — proves the feature works end-to-end once implemented. Not a spec of
behavior (see `spec.md`) or of internals (see `data-model.md` / `research.md`). Builds on the
sibling feature's own quickstart (`specs/001-metacritic-game-tracker/quickstart.md`) — start
there for infrastructure/migrations/running the two processes; this guide only covers what's
new.

## Prerequisites

- Sibling feature's quickstart steps 1-3 done: infrastructure up, migrations applied
  (including this feature's `sql/migrations/007_review_refresh.sql`), `app` + `worker`
  running.
- At least one game already cataloged with both review summaries generated (run the existing
  ingestion quickstart, or seed directly).

## 1. Confirm the initial pipeline records counts

1. Trigger or wait for a normal ingest run to catalog a new game (sibling quickstart §4/§8).
2. Inspect that game's `review_summaries` rows (both audiences): `review_count_at_generation`
   must be populated (not null, not zero unless that audience genuinely had zero reviews at
   generation time).

**Pass condition**: matches spec.md User Story 1, Acceptance Scenario 3.

## 2. Confirm a recheck without meaningful growth leaves the summary alone

1. Pick a cataloged game whose `review_summaries.review_count_at_generation` is close to its
   actual current Metacritic review count (freshly ingested games qualify).
2. Wait for (or manually trigger) a refresh pass covering that game.
3. Confirm in `pipeline_runs` a row with `stage = 'review_refresh'` appears for that run.
4. Confirm the game's `games.reviews_last_checked_at` advanced, but its `review_summaries`
   rows (`summary_text`, `review_count_at_generation`, `generated_at`) are unchanged, and no
   new `llm_calls` row was written for this game.

**Pass condition**: matches spec.md User Story 2, Acceptance Scenarios 2-3.

## 3. Confirm a recheck with significant growth regenerates the summary

1. Pick (or seed) a cataloged game and set its `review_summaries.review_count_at_generation`
   for one audience well below that audience's actual current Metacritic review count — enough
   to clear `review_refresh.growth_threshold_pct` (default 25%; see `/monitoring/config`).
2. Also set `games.reviews_last_checked_at` to `NULL` or far enough in the past to be due under
   `review_refresh.recent_tier_days` / `mid_tier_days` for that game's age.
3. Wait for (or manually trigger) a refresh pass.
4. Confirm that audience's `review_summaries` row changed: new `summary_text`, new
   `review_count_at_generation` matching the freshly observed count, updated `generated_at`,
   and a new `llm_calls` row recorded against it.
5. Confirm the *other* audience, if its growth stayed under threshold, was left untouched.

**Pass condition**: matches spec.md User Story 1, Acceptance Scenarios 1-2.

## 4. Confirm the decay curve and cutoff

1. Seed three games at different ages relative to `first_seen_at`: under 1 week, between 1 and
   4 weeks, and past `review_refresh.max_age_weeks` (default 4 weeks).
2. Run several refresh passes over simulated time (or inspect the due-selection query directly
   against seeded `reviews_last_checked_at` values).
3. Confirm the under-1-week game is selected roughly every `recent_tier_days` (default 3), the
   1-4-week game roughly every `mid_tier_days` (default 7), and the past-cutoff game is never
   selected regardless of how long it's been since its last check.

**Pass condition**: matches spec.md User Story 2, Acceptance Scenario 1; spec.md SC-003.

## 5. Confirm the refresh pass never blocks new-game discovery

1. While a refresh pass has games queued (e.g. many games due at once), trigger a manual
   ingest run (`/monitoring` → Run now, per the sibling feature's operator console).
2. Confirm the ingest run's `pipeline_runs` row completes in line with its usual duration —
   unaffected by how many games were due for a refresh recheck in the same tick.

**Pass condition**: matches spec.md SC-004.

## 6. Full quality gate (Constitution Principle IV)

```bash
poetry run ruff check .
poetry run tach check
poetry run pytest tests/ -q
```

All three must be clean before the feature is considered done.
