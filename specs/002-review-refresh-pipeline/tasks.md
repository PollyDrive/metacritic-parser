# Tasks: Review Refresh Pipeline

**Input**: Design documents from `/specs/002-review-refresh-pipeline/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md), [data-model.md](data-model.md), [quickstart.md](quickstart.md)

**Revision 1 note**: This is the first `tasks.md` for this feature, but substantial groundwork was
already built directly against spec.md/plan.md/data-model.md before this file existed
(`application/enrichment.py`'s `ReviewEnrichmentUseCase`, `scripts/run_scheduler.py`'s
`_run_review_refresh`, `sql/migrations/007_run_kind.sql`/`010_.../`011_...sql`,
`infrastructure/scraper/review_api.py`'s platform-scoped JSON review API client). Inspection of
that code against spec.md/data-model.md/research.md surfaced three real divergences this task
list exists to close or reconcile, rather than generating tasks against docs known to be stale:

1. **Growth-threshold model shipped differently than documented.** spec.md FR-006 and
   data-model.md describe a *percentage* of the recorded count (`review_refresh.growth_threshold_pct`,
   default 0.25). What's actually built and seeded (`sql/migrations/011_review_count_and_threshold.sql`)
   is `reviews.growth_threshold`, a flat absolute review-count delta (default 10), compared against
   the *winning platform's* `total_reviews_count` (`pick_best_platform` in
   `infrastructure/scraper/review_api.py`) — not a percentage, and not a sum across platforms as
   research.md §1 originally decided. This is simpler and already working (module docstring in
   `application/enrichment.py` explains why: reviews are split per platform, so summarizing off
   the platform with the most reviews is more representative than summing incomparable pools).
   **Decision for this task list: keep the shipped absolute-count-against-winning-platform design**
   — rewriting a working, already-reasoned-through mechanism to match a percentage-based spec
   written before this was built would be net-negative. Phase 4 below updates spec.md/data-model.md/
   research.md wording to match, the same way spec 001's FR-006 documents its own
   implementation-time correction.
2. **FR-010 (decay tiers/threshold/cutoff adjustable without a code change) is unmet for the decay
   tiers.** `domain/rules.py`'s `calculate_next_refresh` hardcodes `7`/`28` days and `+3`/`+7` day
   intervals as Python literals — `tests/domain/test_rules.py`'s existing tests only assert those
   hardcoded values. No `review_refresh.recent_tier_days`/`mid_tier_days`/`max_age_weeks` config
   keys exist. (`reviews.growth_threshold` itself IS already a runtime_config key, so FR-010 is
   met for the threshold — only the decay tiers need this fix.)
3. **FR-012 (younger-due-games-first when a pass can't process everything) is entirely
   unimplemented**, and so is the per-tick cap plan.md/research.md §5 describe
   (`review_refresh.games_per_run`). `BackfillEnrichmentUseCase._games_missing` in
   `application/backfill.py` has an `ORDER BY`/`LIMIT` only on its `playthrough` branch
   (`tests/application/test_backfill.py::test_games_missing_for_playthrough_orders_by_best_metascore_then_recency`);
   its `critic_summary`/`user_summary` branch — the one `_run_review_refresh` actually drives — has
   neither, so every due game is fetched and processed in arbitrary DB order every tick.

**Tests**: NOT optional — Constitution Principle I ("Test-First, NON-NEGOTIABLE"). Deterministic
logic (decay-tier resolution, due-selection ordering, growth-threshold arithmetic) is tested
directly; `AsyncMock` is reserved for the DB session and external HTTP/LLM clients, consistent
with spec 001.

**Organization**: Tasks are grouped by user story (P1/P2 from spec.md). Foundational holds the
three fixes above because both user stories depend on them being correct.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: US1/US2, matching spec.md's priorities

---

## Phase 1: Foundational (Blocking Prerequisites)

**Purpose**: Make the decay curve and the due-game selection actually match FR-004/FR-010/FR-012 —
both user stories depend on this being correct, since US1's regeneration correctness assumes the
right games are selected in the first place, and US2 *is* this selection logic.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

### Tests for Foundational Components

> Write these FIRST, confirm they FAIL before implementing (Constitution Principle I)

- [X] T001 [P] Unit tests for `calculate_next_refresh` in `domain/rules.py` reading decay-tier
      bounds (recent-tier days, mid-tier days, max-age weeks) from parameters instead of the
      hardcoded `7`/`28`/`3`/`7` literals — extend `tests/domain/test_rules.py`'s existing
      `test_calculate_next_refresh_for_game_*` tests to pass explicit non-default tier values and
      confirm the result changes accordingly (FR-004, FR-010)
- [X] T002 [P] Unit test: `BackfillEnrichmentUseCase._games_missing("critic_summary")` (and
      `"user_summary"`) orders due games by `GameORM.first_seen_at` descending (youngest first)
      and is capped by a `limit` parameter — mirror the existing
      `test_games_missing_for_playthrough_orders_by_best_metascore_then_recency` pattern in
      `tests/application/test_backfill.py` (FR-012, research.md §5)
- [X] T003 [P] Unit test: `BackfillEnrichmentUseCase.run()` passes `review_refresh.games_per_run`
      through to `_games_missing`'s cap when invoked for the `review_refresh` stage, and passes no
      cap (today's unbounded behavior) for `detail_backfill`/playthrough — `tests/application/test_backfill.py`
      (FR-012, research.md §5)

### Implementation for Foundational Components

- [X] T004 Add `review_refresh.recent_tier_days` (default `3`, bounds 1-30),
      `review_refresh.mid_tier_days` (default `7`, bounds 1-90), and `review_refresh.max_age_weeks`
      (default `4`, bounds 1-52) to `runtime_config` — write
      `sql/migrations/012_review_refresh_decay_config.sql` (FR-010; makes T001 pass)
- [X] T005 Change `calculate_next_refresh(release_date, current_time, recent_tier_days,
      mid_tier_days, max_age_weeks)` in `domain/rules.py` to take the three tier values as
      parameters instead of hardcoded literals; update its one caller in
      `application/enrichment.py` (`ReviewEnrichmentUseCase.run()`) to read
      `review_refresh.recent_tier_days`/`mid_tier_days`/`max_age_weeks` from `RuntimeConfig` and
      pass them through (depends on T004; makes T001 pass)
- [X] T006 Add `order_by=GameORM.first_seen_at.desc()` and an optional `limit` parameter to
      `BackfillEnrichmentUseCase._games_missing`'s `critic_summary`/`user_summary` branch in
      `application/backfill.py`; thread a `games_per_run: int | None` parameter through `run()`
      (`None` preserves today's unbounded behavior for `detail_backfill`); update
      `scripts/run_scheduler.py`'s `_run_review_refresh` to read `review_refresh.games_per_run`
      and pass it as the cap (depends on T005 only insofar as both touch `application/enrichment.py`'s
      call site — otherwise independent; makes T002/T003 pass)

**Checkpoint**: decay tiers and the growth threshold are both operator-tunable (FR-010 fully met);
a review-refresh tick processes at most `review_refresh.games_per_run` games, youngest-due first
(FR-012).

---

## Phase 2: User Story 1 - Summaries Stay Representative as Reviews Accumulate (Priority: P1)

**Goal**: A game's critic/user summary is regenerated once its review count has grown
meaningfully past what it was last summarized against, independently per audience; the count a
summary was generated at is always recorded, from the very first summarization onward.

**Independent Test**: Seed a cataloged game with a recorded review count and an existing summary,
simulate its actual review count having grown well past that recorded count, run a refresh pass,
confirm the summary and recorded count both update.

### Tests for User Story 1

- [X] T007 [P] [US1] Unit test: `ReviewEnrichmentUseCase.run()` regenerates the critic summary and
      updates `review_summaries.total_reviews_count` when the winning platform's review count has
      grown by at least `growth_threshold` over the recorded value, while a `user` audience whose
      growth stays under threshold in the same call is left with its existing `summary_text`/
      `total_reviews_count`/`generated_at` untouched — extend `tests/application/test_enrichment.py`
      (FR-006, FR-007, FR-008, FR-009)
- [X] T008 [P] [US1] Unit test: a `total_reviews_count` of `0` (no prior summary for that audience)
      always clears the threshold regardless of `growth_threshold`'s configured value —
      `tests/application/test_enrichment.py` (Edge Cases: zero-base growth; FR-006)
- [X] T009 [P] [US1] Unit test: the initial ingest pipeline's own enrichment call
      (`application/ingest.py`'s inline `_try_enrich` → `ReviewEnrichmentUseCase.run()`) writes
      `review_summaries.total_reviews_count` at first-time creation, without depending on a later
      refresh pass ever running — `tests/application/test_ingest_dedup.py` or
      `tests/application/test_enrichment.py` (FR-002; Acceptance Scenario 3)
- [X] T010 [P] [US1] Unit test: an observed review count *lower* than the recorded
      `total_reviews_count` (e.g. Metacritic removed reviews) is not growth, does not trigger
      regeneration, and does not change the recorded count — `tests/application/test_enrichment.py`
      (Edge Cases; FR-011)
- [X] T011 [P] [US1] Unit test: a game still missing its very first summary for an audience (prior
      summarization attempt failed) is treated as recorded-count `0` and a non-zero observed count
      triggers the first summary for that audience, rather than waiting for a separate gap-filling
      pass — `tests/application/test_enrichment.py` (Edge Cases)

### Implementation for User Story 1

- [X] T012 [US1] Close any gap T007-T011 surface in `ReviewEnrichmentUseCase._fetch_due`'s due
      calculation (`application/enrichment.py`) — the `due = previous_total == 0 or
      (pick.best_review_count - previous_total) >= growth_threshold` logic already exists; this
      task is verification-and-fix, not a rewrite, since the mechanism is already shipped
      (depends on T007-T011)
- [X] T013 [US1] Close any gap T009 surfaces in `application/ingest.py`'s inline enrichment call
      path so first-time `total_reviews_count` recording is confirmed independent of the refresh
      pass (depends on T009)

**Checkpoint**: User Story 1 independently functional and tested — summaries demonstrably update
when growth clears the threshold, per audience, and never regress when it doesn't.

---

## Phase 3: User Story 2 - Refresh Effort Concentrates Where It Still Matters (Priority: P2)

**Goal**: Revisit frequency decays by game age; a capped, prioritized pass never lets a backlog of
older games starve younger ones; a recheck that doesn't clear the growth threshold still updates
what it cheaply can (userscore pills, last-checked bookkeeping) without spending an LLM call; the
refresh pass never delays new-game discovery.

**Independent Test**: Seed games of varying ages and growth since their last summary; run the
refresh pass repeatedly; confirm younger games are revisited more often and sub-threshold growth
never regenerates a summary.

### Tests for User Story 2

- [X] T014 [P] [US2] Unit test: with `review_refresh.recent_tier_days=3`/`mid_tier_days=7`/
      `max_age_weeks=4` (from Foundational), a game under 1 week old is due every 3 days, a game
      1-4 weeks old is due every 7 days, and a game past 4 weeks is never selected again by
      `calculate_next_refresh` regardless of how long it's been — `tests/domain/test_rules.py`
      (FR-004, SC-003; depends on T005)
- [X] T015 [P] [US2] Unit test: a recheck whose growth doesn't clear the threshold still updates
      every platform's `userscore` pill from the same stats sweep (already implemented — the
      `pick_best_platform` sweep in `application/enrichment.py` runs before the due-check) and
      advances `games.next_refresh_at`, without calling `summarize`/writing a new `llm_calls` row
      — `tests/application/test_enrichment.py` (FR-005, FR-007, SC-002)
- [X] T016 [P] [US2] Unit test: `BackfillEnrichmentUseCase.run()` for the `review_refresh` stage
      processes at most `review_refresh.games_per_run` games per call even when more are due, and
      the ones actually processed are the youngest-due — `tests/application/test_backfill.py`
      (FR-012, SC-003; depends on T006)
- [X] T017 [US2] Test confirming a manual ingest run's `pipeline_runs` timing/behavior is
      independent of how many games are queued for `review_refresh` in the same worker tick —
      `scripts/run_scheduler.py` already runs `review_refresh`/`playthrough` on their own
      `interval_hours` cadence, separate from ingest's; assert this holds via
      `infrastructure/scheduler/tick.py`'s `stage_due` logic — `tests/infrastructure/scheduler/test_tick.py`
      (FR-003, SC-004)

### Implementation for User Story 2

Foundational (T004-T006) plus `application/enrichment.py`'s existing stats-sweep-before-due-check
design cover this story's mechanics. Address anything T014-T017 surface directly in
`domain/rules.py` (decay tiers), `application/backfill.py` (ordering/cap), or
`application/enrichment.py` (userscore-refresh-without-LLM path) as needed — no new module is
anticipated.

**Checkpoint**: Both user stories independently functional — the mandatory scope of this feature
is complete.

---

## Phase 4: Polish

- [X] T018 [P] Update spec.md's FR-006 (and FR-010's threshold clause) to describe the as-shipped
      absolute-count threshold (`reviews.growth_threshold`, compared against the winning
      platform's `total_reviews_count` via `pick_best_platform`) instead of "a configured
      percentage of that recorded count" — mirror how spec 001's FR-006 documents its own
      implementation-time correction inline
- [X] T019 [P] Update data-model.md: remove the undocumented-as-unbuilt
      `games.reviews_last_checked_at` column (superseded — `games.next_refresh_at` alone drives
      due-selection per `application/enrichment.py`), replace `review_refresh.growth_threshold_pct`
      with the actually-seeded `reviews.growth_threshold` (absolute int,
      `sql/migrations/011_review_count_and_threshold.sql`), and add the
      `review_refresh.recent_tier_days`/`mid_tier_days`/`max_age_weeks` keys from T004
- [X] T020 [P] Update research.md §1: the shipped design compares each audience's *winning
      platform* review count (`pick_best_platform`) against the recorded count, not a sum across
      all platforms as originally decided there — document the change and the reasoning already
      captured in `application/enrichment.py`'s module docstring
- [ ] T021 Walk through quickstart.md's 6 scenarios manually against a running instance
      (`app` + `worker` both up), correcting any step that still references
      `reviews_last_checked_at` or a percentage threshold once T018-T020 land
- [ ] T022 Full quality gate: `poetry run ruff check .`, `poetry run tach check`,
      `poetry run pytest tests/ -q` — all clean (Constitution Principle IV)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Foundational (Phase 1)**: No dependencies on this feature's other phases — BLOCKS both user
  stories (spec 001's existing tables/config mechanism are prerequisites, already in place)
- **User Story 1 (Phase 2)**: Depends on Foundational (correct due-selection feeds correct
  regeneration decisions)
- **User Story 2 (Phase 3)**: Depends on Foundational; independently testable from US1 (its tests
  exercise the selection/decay mechanics directly, not summary content)
- **Polish (Phase 4)**: Depends on both user stories being complete

### Parallel Opportunities

- T001, T002, T003 (Foundational tests) in parallel — distinct assertions, though T002/T003 touch
  the same test file and should land as one edit if picked up together
- T007-T011 (US1 tests) in parallel — distinct test functions
- T014-T016 (US2 tests) in parallel; T017 touches a different test file, also parallel
- T018, T019, T020 (doc updates) in parallel — distinct files

---

## Implementation Strategy

### MVP First

1. Phase 1 (Foundational) → Phase 2 (User Story 1)
2. **STOP and VALIDATE**: run quickstart.md §1-3 against User Story 1 alone
3. User Story 1 alone already delivers the feature's core promise (spec.md's "Why this priority");
   User Story 2 is what makes running it continuously affordable

### Incremental Delivery

1. Foundational → decay tiers and due-game selection are both correct and configurable
2. + User Story 1 → summaries demonstrably refresh when growth warrants it (MVP)
3. + User Story 2 → refresh effort is capped, prioritized, and cheap when growth doesn't warrant
   regeneration — completes this feature's scope
4. Polish → documentation catches up to the shipped design, quality gate green
