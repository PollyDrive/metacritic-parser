# Tasks: Metacritic Game Tracker

**Input**: Design documents from `/specs/001-metacritic-game-tracker/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md), [data-model.md](data-model.md), [contracts/web-ui.md](contracts/web-ui.md), [quickstart.md](quickstart.md)

**Revision 6** — three fixes from `/speckit-analyze`'s first run: (F1) FR-010 conflicted with FR-024 (regenerate-on-every-recrawl vs. never-repeat-enrichment) — FR-010 reworded to match what's actually built (spec.md, data-model.md, research.md §7); (C1) no task extracted candidate game slugs from the "New Releases"/"See All" listing pages — added `T013a`/`T025a` (`list_games()`, research.md §9.1); (E1) `dq.max_reject_ratio` was a seeded config key with no implementing task — added `T013b`/`T028a` (batch-level reject-ratio circuit breaker, research.md §14.2).

**Revision 5** — monitoring scope cut down hard: no Grafana, no dashboard, no data-quality rule-catalogue table, no raw-payload landing layer. Kept: email alerting via Resend API, `llm_calls` + `meta.llm_model_costs` (every LLM call, its cost) and application logging at `CRITICAL`/`ERROR` for real failures — that is the entire observability surface for this project now (research.md §13). Concretely vs. revision 4:

- **Removed**: the Grafana dashboard/datasources under `monitoring/`, the `dq_rule_results` rule-catalogue table, the `raw_pages` landing layer, the frozen-evaluation-set practice, `pipeline_findings` (unused).
- **Kept as plain code, not tables**: Gate A (source-schema conformance) and Gate B (record validity) still run — as functions in `infrastructure/dq/gates.py` that log `CRITICAL` or write to the existing `pipeline_rejects`, not into a dedicated metrics table.
- **Kept because they're correctness fixes, not monitoring**: the pagination cursor circuit-breaker (a broken run must not advance `ingest_state`), the backfill derived work queue (FR-023), `runtime_config` (a separate feature request, unrelated to this cut), the out-of-process scheduler.

Carried forward from revision 3 (architecture review #1 + live inspection of Metacritic's markup + data-engineering pass), unaffected by this cut:

- Anti-bot hardening dropped — measured, not assumed: plain `curl` gets `200` on every page this service reads (research.md §5).
- Extraction via the embedded Nuxt SSR payload, not CSS selectors (research.md §9).
- Dedup key is Metacritic's stable numeric game id, not the slug (research.md §10).
- Enrichment strictly downstream of dedup (FR-024) — quota spend tracks new games, not pagination throughput (research.md §6).
- Ingest state made real: pagination cursor + daily progress (research.md §12).
- Operational settings in `runtime_config` with an operator UI (FR-025/026, research.md §11).

**Tests**: NOT optional — Constitution Principle I ("Test-First, NON-NEGOTIABLE") requires a failing test before any production code. Deterministic code (payload extraction, rules, repository queries, scheduler due-checks, config validation) is tested directly; `AsyncMock` is reserved for the DB session and external HTTP.

**Organization**: Tasks are grouped by user story (P1-P5 from spec.md). Ingestion has no user story of its own — the brief frames it as background system behavior — so it sits in Phase 2 (Foundational); every catalog story is still independently testable against seeded fixture data.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: US1-US5, matching spec.md's priorities

---

## Phase 1: Setup

- [X] T001 Create `scripts/migrate.py`: idempotent runner applying `sql/migrations/*.sql` in filename order, tracking applied filenames in a `schema_migrations` table (research.md §1)
- [X] T002 [P] Update the `migrate` target in `Makefile` to run `poetry run python scripts/migrate.py` instead of `alembic upgrade head`
- [X] T003 [P] Remove the `alembic` dependency from `pyproject.toml` (`poetry remove alembic`, then `poetry lock`)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Schema, config layer, extraction, dedup, data-quality gates, enrichment, backfill, and the out-of-process scheduler.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

### Tests for Foundational Components

> Write these FIRST, confirm they FAIL before implementing (Constitution Principle I)

- [X] T004 [P] Unit tests for `domain/rules.py` — source selection (new day → New Releases; same-day → See All at the stored cursor; top-up from See All when New Releases is short, FR-005), day rollover in the configured timezone, cursor advancement — in `tests/domain/test_rules.py`
- [X] T005 [P] Unit tests for genre normalization (dedupe case-insensitively, trim) — never loads the catalog — in `tests/domain/test_similar_rules.py`. **Revised during implementation**: similar-games is genre-overlap, not a `relatedGameId` list — that field turned out to be a per-platform cross-reference to the same game, not other games (research.md §4).
- [X] T006 [P] Unit tests for `infrastructure/scraper/payload.py` — extracts the Nuxt SSR state blob and resolves its indexed references into `metacritic_id`, title, slug, description, developer, platforms with per-platform Metascore/Userscore ("tbd" → `None`), video, `genres` list — against a saved fixture of a real game page, in `tests/infrastructure/scraper/test_payload.py`
- [X] T007 [P] Unit tests for review-subpage parsing (`/critic-reviews`, `/user-reviews`) producing a bounded review sample, in `tests/infrastructure/scraper/test_review_parser.py`
- [X] T008 [P] Unit test: a block/challenge response (403/429/interstitial) raises a typed error and is classified with its own `reason_code` — never parsed as "zero games found" (research.md §5) — in `tests/infrastructure/scraper/test_block_detection.py`
- [X] T009 [P] Unit tests for `infrastructure/db/repositories.py` upsert keyed on `metacritic_id`: insert when absent, update when present, and **a changed slug for an existing id updates rather than inserting a duplicate** (research.md §10), in `tests/infrastructure/db/test_repositories.py`
- [X] T010 [P] Unit tests for `infrastructure/scheduler/tick.py` — due-ness computed from the last completed `ingest` row in `pipeline_runs` (a simulated restart does NOT reset the schedule), scheduled runs skipped outside the active-hours window and when `ingest.enabled` is false, a pending `run_requests` row runs regardless of both — in `tests/infrastructure/scheduler/test_tick.py`
- [X] T011 [P] Unit tests for `infrastructure/config/runtime.py` — values re-read per run, out-of-range writes rejected server-side (e.g. `scraper.request_delay_seconds = 0`), unknown keys rejected, type coercion per `value_type` — in `tests/infrastructure/config/test_runtime.py`
- [X] T012 [P] Unit tests for `application/backfill.py` — a game present but missing `review_summaries(audience='critic')` is queued even though it was "seen today"; a game inside `enrichment_attempts` backoff is skipped; a game past the attempt ceiling is written to `pipeline_rejects` and its `enrichment_attempts.state` flips to `'abandoned'`; an abandoned game is never re-selected on a later run (FR-023) — in `tests/application/test_backfill.py`
- [X] T012a [P] Unit test for Gate A (source conformance, `infrastructure/dq/gates.py`): a payload missing a required key logs `CRITICAL`, the run aborts, nothing is written, **and `ingest_state.see_all_next_page` is unchanged** — the cursor must not advance past pages that were never ingested (FR-029, research.md §14.2) — in `tests/infrastructure/dq/test_gate_source.py`
- [X] T012b [P] Unit test for Gate B (record validity, `infrastructure/dq/gates.py`): a record missing `metacritic_id` is written to `pipeline_rejects` and never reaches the catalog; a record missing only `description` **is** admitted and queued for re-extraction (FR-028); a metascore outside 0-100 is treated the same as missing — in `tests/infrastructure/dq/test_gate_record.py`
- [X] T013 [P] Unit test: enrichment is invoked only for games the upsert admitted as new or that are missing an output — re-ingesting an already-enriched game triggers zero LLM and zero YouTube calls (FR-024) — in `tests/application/test_ingest_dedup.py`
- [X] T013a [P] Unit tests for `infrastructure/scraper/parser.py`'s `list_games(html)` — extracts `GameStub` (slug + `metacritic_id`) entries from a saved fixture of the "New Releases" page and of a "See All / Newest" page; returns an empty list (not an error) on a page with zero games (found via `/speckit-analyze`, finding C1 — FR-002/003 need a listing→candidates step that no earlier task covered) — in `tests/infrastructure/scraper/test_list_games.py`
- [X] T013b [P] Unit test: `IngestGamesUseCase` aborts a run and does **not** advance `ingest_state.see_all_next_page` when the share of Gate-B-rejected items exceeds `dq.max_reject_ratio` — distinct from Gate A's hard structural-failure abort (FR-029's second clause, found unimplemented via `/speckit-analyze`, finding E1) — in `tests/application/test_ingest_reject_ratio.py`

### Implementation for Foundational Components

- [X] T014 Write `sql/migrations/003_games.sql` — `games` (with `metacritic_id` bigint unique as the dedup key, `metacritic_slug` as a non-unique attribute, `genres` text[] with a GIN index for the overlap query), `platform_scores`, `review_summaries` per `data-model.md`
- [X] T015 Write `sql/migrations/004_ingest_state.sql` — `ingest_state` (singleton: `current_day`, `day_processed_count`, `day_new_releases_done`, `see_all_next_page`), `enrichment_attempts`, `run_requests` per `data-model.md`
- [X] T016 Write `sql/migrations/005_runtime_config.sql` — `runtime_config` table plus seed rows for every key/default/bound in `data-model.md`'s RuntimeConfig table
- [X] T017 [P] `metacritic_game_tracker/domain/models.py` — `Game`, `PlatformScore`, `ReviewSummary` dataclasses
- [X] T018 `metacritic_game_tracker/domain/rules.py` — source selection, day rollover, cursor advancement, similar-games key derivation (makes T004/T005 pass)
- [X] T019 [P] `metacritic_game_tracker/infrastructure/config/runtime.py` — typed accessor over `runtime_config` with server-side bounds validation and an update path recording `updated_by` (makes T011 pass)
- [X] T020 [P] `metacritic_game_tracker/infrastructure/db/models.py` — SQLAlchemy ORM models for all tables above
- [X] T021 [P] `metacritic_game_tracker/infrastructure/db/session.py` — async engine + sessionmaker from `DATABASE_URL`
- [X] T022 `metacritic_game_tracker/infrastructure/db/repositories.py` — `GameRepository` (upsert by `metacritic_id`, get, list, related lookup) and `IngestStateRepository` (read/advance cursor and daily counters) — depends on T020, T021; makes T009 pass
- [X] T023 [P] `metacritic_game_tracker/infrastructure/scraper/metacritic_client.py` — plain `httpx` with a realistic UA, delay/timeout/retries read from `runtime_config`, and typed block/challenge detection (makes T008 pass)
- [X] T024 [P] `metacritic_game_tracker/infrastructure/scraper/payload.py` — locate the Nuxt SSR state blob and resolve its indexed value references (makes T006 pass)
- [X] T025 `metacritic_game_tracker/infrastructure/scraper/parser.py` — payload → domain fields, plus review-subpage sampling (depends on T024; makes T007 pass)
- [X] T025a `metacritic_game_tracker/infrastructure/scraper/parser.py` — `list_games(html) -> list[GameStub]`: extracts candidate slugs/ids from a "New Releases" or "See All" listing page (research.md §9.1); prefer the page's Nuxt SSR payload if it carries a structured game array, fall back to anchor-tag (`<a href="/game/<slug>/">`) parsing otherwise — this is the step `IngestGamesUseCase`'s "fetch" was missing (depends on T024; makes T013a pass)
- [X] T026 [P] `metacritic_game_tracker/infrastructure/llm/review_summarizer.py` — separate critic/user summaries from the sampled reviews (sizes from `runtime_config`) via `shared.llm_config`, sanitizing scraped text through `shared.guardrail.sanitize_input()` first, recording a row in `llm_calls` per call
- [X] T027 `metacritic_game_tracker/infrastructure/dq/gates.py` — `check_source(payload)` (Gate A: required-key/type check, logs `CRITICAL` and signals abort on failure) and `check_record(record)` (Gate B: identifying fields missing → reject verdict, recoverable fields missing → admit-with-flag verdict) — plain functions, no rule-catalogue table, failures go to `pipeline_rejects` (research.md §14; makes T012a/T012b pass)
- [X] T028 `metacritic_game_tracker/application/ingest.py` — `IngestGamesUseCase`: read config → select source via rules → fetch listing page → **`list_games()`** → **Gate A** (per fetched detail page) → parse → **Gate B** (per record) → **upsert (dedup by `metacritic_id`)** → enrich **only** newly-admitted or still-incomplete games → advance `ingest_state` **only on a non-aborted run** → record `pipeline_runs`/`pipeline_rejects` (depends on T018, T019, T022, T023, T025, T025a, T026, T027; makes T013 pass)
- [X] T028a `metacritic_game_tracker/application/ingest.py` — after Gate B has run over the whole batch, compute `rejected / checked` for the run and abort with `status='failed'` **without advancing `ingest_state`** if it exceeds `dq.max_reject_ratio` — the batch-level counterpart to Gate A's per-payload abort (research.md §14.2; depends on T027, T028; makes T013b pass)
- [X] T029 `metacritic_game_tracker/application/backfill.py` — `BackfillEnrichmentUseCase`: derive the missing-output work queue in SQL (excluding `enrichment_attempts.state = 'abandoned'`), respect backoff, record `stage='backfill'` runs (depends on T022, T026; makes T012 pass)
- [X] T030 `metacritic_game_tracker/infrastructure/scheduler/tick.py` — due-ness from `pipeline_runs`, active-hours + `ingest.enabled` gating from `runtime_config`, pending `run_requests` override (depends on T019, T022; makes T010 pass)
- [X] T031 `scripts/run_scheduler.py` — worker entry point: poll loop calling `tick`, then `IngestGamesUseCase` and `BackfillEnrichmentUseCase` (depends on T028, T029, T030)
- [X] T032 [P] `metacritic_game_tracker/infrastructure/web/app.py` — FastAPI app factory + Jinja2 templates setup
- [X] T033 Update `main.py` to run the web tier only — no scheduler in-process (research.md §3; depends on T032)

**Checkpoint**: `worker` can go from a listing page to candidate games (`list_games`), ingests, dedups, enriches only new/incomplete games, aborts closed (no cursor advance) on either a structural break or a high per-run reject ratio, and backfills gaps; every knob is tunable from the DB; `app` serves requests without duplicating any of it.

---

## Phase 3: User Story 1 - Browse Game Catalog (Priority: P1) 🎯 MVP

**Goal**: A visitor can see a catalog list and open a full detail card for any game.

**Independent Test**: Seed the DB with one processed game (fixture data, no live scrape), load `/games`, confirm brief info; open the game, confirm every field renders.

### Tests for User Story 1

- [X] T034 [P] [US1] Contract test: `GET /games` returns a list showing title/cover/platform/score per game in `tests/contract/test_catalog_list.py`
- [X] T035 [P] [US1] Contract test: `GET /games/{id}` renders developer, description, video link, per-platform scores, and both review summaries; 404 for an unknown id in `tests/contract/test_catalog_detail.py`
- [X] T036 [P] [US1] Unit tests for `ListGames`/`GetGameDetail` use cases (`AsyncMock` repository) in `tests/application/test_catalog.py`

### Implementation for User Story 1

- [X] T037 [US1] `metacritic_game_tracker/application/catalog.py` — `ListGames`, `GetGameDetail` (depends on T022; makes T036 pass)
- [X] T038 [US1] `metacritic_game_tracker/infrastructure/web/routes_catalog.py` — `GET /games`, `GET /games/{id}` (depends on T037; makes T034/T035 pass)
- [X] T039 [P] [US1] `metacritic_game_tracker/infrastructure/web/templates/list.html`
- [X] T040 [P] [US1] `metacritic_game_tracker/infrastructure/web/templates/game_card.html` (developer, description, video link, per-platform scores, critic + user review summaries)
- [X] T041 [US1] Wire `routes_catalog` router into `app.py` (depends on T032, T038)

**Checkpoint**: User Story 1 fully functional and independently testable.

---

## Phase 4: User Story 2 - Filter, Search, and Sort the Catalog (Priority: P2)

**Goal**: A visitor narrows the catalog by platform, title, or rating.

**Independent Test**: Load games spanning platforms/ratings, apply each control independently, verify results.

### Tests for User Story 2

- [X] T042 [P] [US2] Contract test: `GET /games?platform=X` returns only matching games in `tests/contract/test_catalog_filter.py`
- [X] T043 [P] [US2] Contract test: `GET /games?q=<partial>` returns case-insensitive title matches in `tests/contract/test_catalog_search.py`
- [X] T044 [P] [US2] Contract test: `GET /games?sort=rating` orders by best available score in `tests/contract/test_catalog_sort.py`

### Implementation for User Story 2

- [X] T045 [US2] Extend `GameRepository.list()` with `platform` filter, `q` title search, `sort=rating` ordering in `infrastructure/db/repositories.py` (depends on T022)
- [X] T046 [US2] Extend `ListGames` to accept `platform`/`q`/`sort` in `application/catalog.py` (depends on T037, T045)
- [X] T047 [US2] Extend `GET /games` to parse and pass through those query params in `infrastructure/web/routes_catalog.py` (depends on T038, T046)
- [X] T048 [P] [US2] Add platform filter, search box, and sort control to `infrastructure/web/templates/list.html`

**Checkpoint**: User Stories 1 AND 2 both work independently.

---

## Phase 5: User Story 3 - Discover Similar Games (Priority: P3)

**Goal**: A game's card shows other catalog games considered similar, clickable to their own card.

**Independent Test**: Seed two games sharing a related id, open one's card, confirm the other is listed and clicking it navigates to its own card.

### Tests for User Story 3

- [X] T049 [P] [US3] Unit test: similar-games lookup issues **one** `WHERE genres && :genres AND id != :id ORDER BY best_score DESC` query (assert query count — no N+1, no full-catalog load, research.md §4) and returns other catalog games sharing a genre, empty when none qualify, in `tests/infrastructure/db/test_similar_games.py`
- [X] T050 [P] [US3] Contract test: `GET /games/{id}` includes a similar-games section linking to each similar game's own page in `tests/contract/test_catalog_similar.py`

### Implementation for User Story 3

- [X] T051 [US3] Add `get_similar_games(game)` to `infrastructure/db/repositories.py` — single `genres && :genres` overlap query, `id != :id`, ordered by best score, over `domain/rules.py`-normalized genre names (depends on T018, T022; makes T049 pass)
- [X] T052 [US3] Include similar games in `GetGameDetail` in `application/catalog.py` (depends on T037, T051)
- [X] T053 [P] [US3] Add a "similar games" section with links to `infrastructure/web/templates/game_card.html` (depends on T040; makes T050 pass with T052)

**Checkpoint**: User Stories 1-3 all independently functional — mandatory scope complete.

---

## Phase 6: User Story 4 - Playthrough-Based Takeaway (Priority: P4) — optional scope

**Goal**: A game's card shows a short takeaway from its most popular YouTube playthrough, linked to the source video.

**Independent Test**: Run enrichment for a game with a known playthrough, confirm takeaway + link attached; for a game with none, confirm no error and no takeaway section.

### Tests for User Story 4

- [X] T054 [P] [US4] Unit test: `playthrough_finder` picks the most-viewed public video for a title, using a mocked YouTube API response, in `tests/infrastructure/youtube/test_playthrough_finder.py`
- [X] T055 [P] [US4] Unit test: daily budget is read from and written to `youtube_quota_usage` (persisted — a simulated restart does NOT reset the day's spend) and lookup stops cleanly when the budget from `runtime_config` is exhausted, in `tests/infrastructure/youtube/test_quota_budget.py`
- [X] T056 [P] [US4] Unit test: `FindPlaythroughTakeawayUseCase` leaves the game without a takeaway and raises no visitor-facing error when no video is found, in `tests/application/test_playthrough.py`

### Implementation for User Story 4

- [X] T057 [US4] Write `sql/migrations/006_playthrough.sql` — `playthrough_takeaways` and `youtube_quota_usage` per `data-model.md`
- [X] T058 [US4] `infrastructure/youtube/playthrough_finder.py` — budgeted YouTube Data API search (100 units per `search.list`, budget and enable-flag from `runtime_config`) prioritized by Metascore then recency, caption-track fetch, LLM audio-transcription fallback only when captions are absent (makes T054/T055 pass)
- [X] T059 [US4] `application/playthrough.py` — `FindPlaythroughTakeawayUseCase`: sanitize transcript via `shared.guardrail`, summarize via `shared.llm_config`, persist, record `llm_calls` (depends on T058; makes T056 pass)
- [X] T060 [US4] Register playthrough as a third enrichment step in `application/backfill.py`'s derived work queue, so budget-skipped games are retried on later days (depends on T029, T059)
- [X] T061 [P] [US4] Add a conditional playthrough-takeaway section (omitted when absent) to `infrastructure/web/templates/game_card.html` (depends on T040)

**Checkpoint**: User Stories 1-4 functional.

---

## Phase 7: User Story 5 - Operator Console (Priority: P5) — optional scope

**Goal**: An operator watches ingestion live, forces an out-of-schedule run, and retunes settings without a redeploy.

**Independent Test**: Trigger a run manually and watch counters update live; change a setting and confirm the next run uses it.

### Tests for User Story 5

- [X] T062 [P] [US5] Contract test: `GET /monitoring` and `GET /monitoring/config` return `401` without valid basic-auth credentials, `200` with them (FR-026), in `tests/contract/test_monitoring_auth.py`
- [X] T063 [P] [US5] Contract test: `POST /monitoring/run` inserts a `run_requests` row and returns `202` with its id (the web tier does not execute the run); `409` when a run is already `running` or a request is unconsumed, in `tests/contract/test_monitoring_run.py`
- [X] T064 [P] [US5] Contract test: `POST /monitoring/config` persists a valid change with `updated_by`; rejects an out-of-range value (e.g. `scraper.request_delay_seconds = 0`) with `422` leaving **all** stored values untouched; rejects unknown keys — in `tests/contract/test_config_page.py`

### Implementation for User Story 5

- [X] T065 [US5] `infrastructure/web/routes_monitoring.py` — `GET /monitoring`, `GET /monitoring/stream` (SSE), `POST /monitoring/run` (enqueue-only), behind HTTP Basic Auth against `MONITORING_USERNAME`/`MONITORING_PASSWORD` (depends on T022, T030; makes T062/T063 pass)
- [X] T066 [US5] `infrastructure/web/routes_config.py` — `GET`/`POST /monitoring/config`, all-or-nothing save with server-side bounds validation, behind the same basic auth (depends on T019; makes T064 pass)
- [X] T067 [P] [US5] `infrastructure/web/templates/monitoring.html` — status/counters + manual-run button + SSE client script
- [X] T068 [P] [US5] `infrastructure/web/templates/config.html` — every `runtime_config` key with its current value, permitted range, description, and last-changed-by; inline validation messages
- [X] T069 [US5] Wire `routes_monitoring` and `routes_config` routers into `app.py` (depends on T032, T065, T066)

**Checkpoint**: All five user stories independently functional.

---

## Phase 8: Polish

- [X] T070 [P] Audit every `except` in the codebase: each one is either a deliberate, narrow handler for an expected condition or re-raises; no `except: pass`, no per-item handler that only logs and continues (research.md §13)
- [X] T071 [P] Edge-case tests: "tbd" scores render as absent (not `0`), missing video link, a game gaining a new platform on re-crawl, a game whose slug changed, region-locked/deleted playthrough video — in `tests/infrastructure/scraper/test_payload.py`
- [X] T072 Walk through every scenario in `quickstart.md` manually against a running instance (`app` + `worker` both up)
- [X] T073 Full quality gate: `poetry run ruff check .`, `poetry run tach check`, `poetry run pytest tests/ -q` — all clean (Constitution Principle IV)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundational (Phase 2)**: Depends on Setup — BLOCKS all user stories
- **User Story 1 (Phase 3)**: Depends on Foundational only
- **User Story 2 (Phase 4)**: Depends on Foundational + US1 (extends its repository/routes/template)
- **User Story 3 (Phase 5)**: Depends on Foundational + US1 (extends the same card template)
- **User Story 4 (Phase 6)**: Depends on Foundational only — optional scope
- **User Story 5 (Phase 7)**: Depends on Foundational only — optional scope
- **Polish (Phase 8)**: Depends on whichever stories were built

### Parallel Opportunities

- T002/T003 in parallel with each other and with T001
- T004-T013, T013a, T013b (foundational tests) all in parallel — distinct test files
- T017, T019, T020, T021, T023, T024, T026, T032 in parallel (distinct files); T018/T022/T025/T025a/T027/T028/T028a/T029/T030/T031/T033 assemble them and are sequential
- Within each user story, its `[P]` test tasks run in parallel; US4 and US5 can be built concurrently once Foundational is done

---

## Implementation Strategy

### MVP First

1. Phase 1 (Setup) → Phase 2 (Foundational) → Phase 3 (User Story 1)
2. **STOP and VALIDATE**: run `quickstart.md` §4 against User Story 1 alone
3. Smallest deployable increment; User Stories 1-3 together are the full mandatory scope

### Incremental Delivery

1. Setup + Foundational → data flows end-to-end, dedup is stable, gaps self-heal, knobs are tunable
2. + User Story 1 → browsable catalog (MVP)
3. + User Story 2 → filter/search/sort
4. + User Story 3 → similar games (completes mandatory scope per spec.md)
5. + User Story 4 → playthrough takeaways (optional scope)
6. + User Story 5 → operator console (optional scope)

---

## Phase 9: Convergence

- [ ] T074 CRITICAL — Compute and persist `llm_calls.cost_usd` from `meta.llm_model_costs` (rate × `input_tokens`/`output_tokens`) at insert time in `application/enrichment.py` and `application/playthrough.py`, instead of leaving it at its ORM default of `0` — the project's sole real observability table is dead on arrival without this per Constitution (constitution: Security & Data Handling) (missing)
- [ ] T075 Make playthrough video selection match FR-018 ("most popular ... playthrough video"): either select by `view_count` in `infrastructure/youtube/playthrough_finder.py`'s `find_most_relevant_playthrough` (currently returns `candidates[0]`, search-relevance order) and update `tests/infrastructure/youtube/test_playthrough_finder.py` accordingly, or reword FR-018 to state relevance-based selection and align tasks.md's T054 description — pick one, make code/test/spec agree per FR-018 (contradicts)
- [ ] T076 Add a `GameActivityEvent` entity section to data-model.md documenting the `game_activity_events` table (`sql/migrations/008_game_activity_events.sql`), already used by `routes_monitoring.py`, `application/ingest.py`, `application/enrichment.py`, `application/playthrough.py` per plan.md's Phase 1 output (missing)
- [ ] T077 Expand contracts/web-ui.md's `GET /monitoring` section to document the error log, per-run reject/event accordion, playthrough coverage percentage, and cross-game activity feed actually rendered by `routes_monitoring.py`'s `monitoring_status` per plan.md's Phase 1 output (partial)
- [ ] T078 Reword FR-005 in spec.md to state the always-recheck-"See All"-page-1 drift-correction behavior implemented in `domain/rules.py`'s `plan_ingest()` (topup runs every subsequent-day run, not only on a New-Releases shortfall) (contradicts)
