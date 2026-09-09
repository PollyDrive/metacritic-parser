# Phase 1 Data Model: Metacritic Game Tracker

Entities derived from `spec.md`'s Key Entities section, refined with concrete fields/types.
Tables not listed here (`meta.llm_model_costs`, `pipeline_runs`, `pipeline_rejects`,
`llm_calls`) already exist under `sql/migrations/000-002` and are reused as-is by this
feature. `meta.llm_model_costs` and `llm_calls` are the two tables this project's
observability is actually scoped to: every LLM call, its cost, and its model — nothing
beyond that runs through a dashboard (research.md §13).

## Game

Core catalog entity. One row per Metacritic game page, regardless of how many platforms
it's released on.

| Field | Type | Notes |
|---|---|---|
| `id` | serial PK | internal surrogate key |
| `metacritic_id` | bigint, unique, not null | **the dedup key** (FR-007) — Metacritic's stable numeric game id from the SSR payload (e.g. `1300501979`), immune to renames (research.md §10) |
| `metacritic_slug` | text, not null | URL slug (`/game/<slug>/`) — secondary identifier for building links and debugging; may change over time, so NOT the identity |
| `title` | text, not null | |
| `cover_image_url` | text | |
| `developer` | text | |
| `description` | text | |
| `video_url` | text, nullable | not every game has one |
| `release_date` | date, nullable | captured from Metacritic; drives the decayed TTL refresh logic |
| `genres` | text[], not null default `'{}'` | genre names from the SSR payload's `genres` list (e.g. `Action RPG`); FR-016's similar-games query reads this — **not** `relatedGameId`, which turned out to be a per-platform cross-reference to the same game, not a recommendations list (research.md §4, corrected during implementation) |
| `first_seen_at` | timestamptz, not null default now() | |
| `last_updated_at` | timestamptz, not null default now() | bumped on every re-crawl (FR-007). **Never** means "fully enriched" — see State Transitions |
| `next_refresh_at` | timestamptz, nullable | computed from `release_date` based on Decayed TTL rules. Determines when review summaries should be re-generated. |

**Validation**: `metacritic_id` required and unique — this is what makes an ingestion run an
upsert instead of a duplicate insert (FR-007). `title` required. A changed `metacritic_slug`
for an existing `metacritic_id` is a normal attribute update, not a new game.

## PlatformScore

One row per (game, platform) pair — a game with 3 platform releases has 3 rows.

| Field | Type | Notes |
|---|---|---|
| `id` | serial PK | |
| `game_id` | FK → Game, not null | |
| `platform` | text, not null | e.g. `PS5`, `Switch 2`, `PC` |
| `metascore` | integer, nullable | null = Metacritic shows "tbd" |
| `userscore` | numeric(3,1), nullable | Metacritic userscore is 0.0-10.0; null = "tbd" |
| `updated_at` | timestamptz, not null default now() | |

**Validation**: unique on `(game_id, platform)`. `metascore` in `[0,100]` when present;
`userscore` in `[0.0,10.0]` when present.

## ReviewSummary

Two rows per game at most — one `critic`, one `user` — kept separate per FR-008/FR-009.

| Field | Type | Notes |
|---|---|---|
| `id` | serial PK | |
| `game_id` | FK → Game, not null | |
| `audience` | text, not null, check in `('critic','user')` | |
| `summary_text` | text, not null | what's liked/disliked, per FR-008/FR-009 |
| `generated_at` | timestamptz, not null default now() | set once, when the row is first created by the backfill path (FR-010); never regenerated for a game that already has one (FR-024) |
| `llm_call_id` | FK → `llm_calls.id`, nullable | traceability to the generating call/cost |

**Validation**: unique on `(game_id, audience)` — regeneration is an update, not a new row.

## PlaythroughTakeaway *(optional scope, US4)*

At most one row per game.

| Field | Type | Notes |
|---|---|---|
| `id` | serial PK | |
| `game_id` | FK → Game, unique, not null | |
| `video_url` | text, not null | |
| `video_view_count_at_selection` | bigint | for tie-breaking / re-evaluation later |
| `takeaway_text` | text, not null | |
| `generated_at` | timestamptz, not null default now() | |
| `llm_call_id` | FK → `llm_calls.id`, nullable | |

**Validation**: absence of a row is valid (edge case: "no findable playthrough" — no error).

## IngestionRun

Already modeled by the existing `pipeline_runs` table (`sql/migrations/001_pipeline.sql`);
this feature's `IngestGamesUseCase` writes one row per run with `stage='ingest'` and
`source` set to `'new_releases'` or `'see_all_newest'`. The backfill stage writes rows with
`stage='backfill'`. **The worker also reads this table to decide whether a run is due**
(latest `completed` `ingest` run's `finished_at`), so the schedule survives restarts
(research.md §3).

`meta` is a free-form JSONB scratch space (e.g. the `runtime_config` snapshot a run used) —
not a dashboard contract, since there is no dashboard. Its columns
(`items_in/accepted/rejected/deferred/errored`) are what `IngestGamesUseCase` and
`BackfillEnrichmentUseCase` actually read and write; nothing here exists solely to feed a panel.

**Markup changes are logged, not metriced**: a Metacritic markup change almost never raises —
the payload shape shifts, fields resolve to `None`, and the run would otherwise complete
cleanly with zero errors. `infrastructure/dq/gates.py` (below) logs at `CRITICAL` when a
required field comes back empty, so this shows up in the application log even without a
dedicated completeness metric.

## IngestState

Singleton row holding the pagination cursor and per-day progress. **Added after the
data-engineering review** — FR-003 ("advance to the next page each run") and FR-004 ("games not
already processed today") were both asserted by the spec with nowhere to store the state they
require (research.md §12).

| Field | Type | Notes |
|---|---|---|
| `id` | smallint PK, check `id = 1` | singleton |
| `current_day` | date, not null | the day `day_processed_count` refers to, in `ingest.timezone` |
| `day_processed_count` | integer, not null default 0 | resets when `current_day` rolls over (FR-005) |
| `day_new_releases_done` | boolean, not null default false | whether today's "New Releases" pass is exhausted (drives the FR-005 top-up) |
| `see_all_next_page` | integer, not null default 1 | pagination cursor into "See All / Newest" (FR-003) |
| `updated_at` | timestamptz, not null default now() | |

**Why a cursor is not optional**: without it, a restart silently resumes from page 1 and
re-scrapes the same games every hour indefinitely — runs complete, counters look healthy, and
nothing new ever enters the catalog.

## Data-quality gates (no dedicated table)

Two checks run in `infrastructure/dq/gates.py`, per research.md §14 — as plain code, not as a
rule-catalogue table with severity tiers. This project's observability is scoped to LLM
calls/cost + critical logs; a validation failure is exactly that: a `CRITICAL`-level log line
plus (for per-record failures) a row in the existing `pipeline_rejects` table with a
`reason_code` — no separate aggregation table, no dashboard.

**Gate A — source conformance** (raw payload, before parsing): does the SSR payload contain
`id`, `title`, `slug`, `description`, `platforms`, `criticScoreSummary` in the expected shape?
On failure: log `CRITICAL`, **abort the run without advancing `ingest_state.see_all_next_page`**
(the pagination cursor — see below), write nothing. This is the one behavior from §14 kept
verbatim, because it is a correctness requirement, not a monitoring nicety: a broken run that
advanced the cursor anyway would skip pages of games permanently, since the listing only moves
forward (research.md §14.2).

**Gate B — record validity** (parsed record, per item): `metacritic_id`/`title`/≥1 platform
present → reject to `pipeline_rejects` if missing (record cannot be identified or displayed at
all). `description`/`developer`/`cover_image_url` missing → the record is still admitted (the
scores are usable) and queued through the existing backfill work queue for re-extraction, same
as a missing review summary (see State Transitions below) — no separate tracking mechanism.

## RuntimeConfig

Operator-tunable settings, edited live via the config UI and re-read by the worker at the start
of each run (research.md §11). **Operational values only — never secrets.**

| Field | Type | Notes |
|---|---|---|
| `key` | text PK | e.g. `ingest.games_per_run` |
| `value` | text, not null | serialized per `value_type` |
| `value_type` | text, not null, check in `('int','float','bool','string','time')` | |
| `min_value` / `max_value` | numeric, nullable | server-side bounds for numeric keys |
| `description` | text | shown in the UI |
| `updated_at` | timestamptz, not null default now() | |
| `updated_by` | text | operator username from basic auth |

Seeded keys and defaults:

| Key | Default | Bounds | Meaning |
|---|---|---|---|
| `ingest.enabled` | `true` | — | master switch for scheduled ingestion |
| `ingest.runs_per_hour` | `1` | 1-12 | cadence (FR-001) |
| `ingest.games_per_run` | `20` | 1-100 | batch size (FR-004) |
| `ingest.active_hours_start` | `00:00` | — | start of the active window |
| `ingest.active_hours_end` | `24:00` | — | end of the active window; outside it the worker ticks but does not ingest |
| `ingest.timezone` | `UTC` | — | pins the "calendar day" boundary for FR-005 and the active window (research.md §12) |
| `scraper.request_delay_seconds` | `1.5` | 0.5-30 | politeness delay (research.md §5) |
| `scraper.max_retries` | `3` | 0-10 | |
| `scraper.timeout_seconds` | `30` | 5-120 | |
| `reviews.critic_sample_size` | `20` | 1-100 | reviews fed to summarization (research.md §8) |
| `reviews.user_sample_size` | `20` | 1-100 | |
| `enrichment.playthrough_enabled` | `false` | — | US4 master switch (optional scope) |
| `enrichment.youtube_daily_search_budget` | `80` | 0-100000 | quota rail; correct value depends on backfill vs steady state (research.md §6) |
| `backfill.max_attempts` | `5` | 1-20 | attempt ceiling before abandoning (FR-023) |
| `backfill.backoff_base_minutes` | `30` | 1-1440 | exponential backoff base |
| `dq.max_reject_ratio` | `0.25` | 0.01-1.0 | share of a run's items failing Gate B's critical checks that aborts the run without advancing the cursor (research.md §14.2) |

**Validation**: writes MUST be bounds-checked server-side, not only in the browser. A
`request_delay_seconds` of `0` would turn the service into an accidental denial-of-service
against Metacritic, so the floor is enforced where it cannot be bypassed.

## EnrichmentAttempt

Retry/backoff bookkeeping for the derived work queue (FR-023, research.md §7). One row per
(game, enrichment step) — created only once a step has failed at least once.

| Field | Type | Notes |
|---|---|---|
| `id` | serial PK | |
| `game_id` | FK → Game, not null | |
| `step` | text, not null, check in `('critic_summary','user_summary','playthrough')` | |
| `attempts` | integer, not null default 1 | |
| `state` | text, not null default `'retrying'`, check in `('retrying','abandoned')` | terminal state for exhausted items |
| `last_error` | text | |
| `last_attempt_at` | timestamptz, not null default now() | |
| `next_retry_at` | timestamptz, not null | exponential backoff |

**Validation**: unique on `(game_id, step)`. A step is eligible for work when its output is
missing AND (no attempt row exists OR (`state = 'retrying'` AND `now() >= next_retry_at`)).
Past `backfill.max_attempts` the row flips to `state = 'abandoned'` and is written to
`pipeline_rejects` with a reason code, so exhausted items stay visible instead of merely absent.

**Why `state` is not redundant with `attempts >= max_attempts`**: the ceiling is a *runtime
config value* (FR-025) that an operator can lower. Deriving abandonment by comparing against the
current setting would silently resurrect or bury work whenever that knob moves. The terminal
state records the decision that was actually made, at the ceiling that was actually in force.
Without this column the eligibility predicate above re-selects exhausted rows forever — the
backoff delays the retry but never stops it.

**Note**: the work queue itself is *not* stored — it is derived per run by asking which games
lack a `review_summaries` row per audience / a `playthrough_takeaways` row. This table only
prevents permanently-failing items from being retried forever.

## RunRequest

Manual out-of-schedule trigger (FR-020), enqueued by the web tier and consumed by the worker
process (research.md §3) — the web service never runs ingestion in-process.

| Field | Type | Notes |
|---|---|---|
| `id` | serial PK | |
| `requested_at` | timestamptz, not null default now() | |
| `picked_up_at` | timestamptz, nullable | null = still pending |
| `run_id` | FK → `pipeline_runs.id`, nullable | set when the worker starts the run |

**Validation**: `POST /monitoring/run` returns `409` when an `ingest` run is currently
`running` or an unconsumed request already exists (contracts/web-ui.md).

## YoutubeQuotaUsage *(optional scope, US4)*

Persisted daily spend against the YouTube Data API budget (research.md §6). Persisted rather
than counted in memory so a worker restart cannot silently reset the counter and blow the
daily quota.

| Field | Type | Notes |
|---|---|---|
| `usage_date` | date PK | |
| `search_calls` | integer, not null default 0 | |
| `units_spent` | integer, not null default 0 | `search.list` = 100 units each |

## Relationships

```text
Game 1──* PlatformScore
Game 1──0..2 ReviewSummary   (audience='critic' | 'user')
Game 1──0..1 PlaythroughTakeaway   (optional scope)
Game.genres ──(overlap query against other rows' Game.genres, ordered by best Metascore)──> "similar games"
ReviewSummary / PlaythroughTakeaway ──*──1 llm_calls   (cost/traceability)
```

## State Transitions

Games have no status column, but — corrected after architecture review #1 — "row exists with
today's `last_updated_at`" is explicitly **not** treated as "fully processed". Completion is
derived per enrichment step from whether its output row exists:

```text
game row exists
├── review_summaries(audience='critic') missing → queued for critic summarization
├── review_summaries(audience='user')   missing → queued for user summarization
└── playthrough_takeaways               missing → queued for playthrough enrichment (optional scope)
```

Enrichment is therefore strictly **downstream of deduplication**: a run's batch is upserted by
`metacritic_id` first, and only games that the upsert admitted as new (or that are still
missing an output) reach summarization and playthrough lookup. Already-known games cost nothing
beyond the fetch — which is what keeps YouTube quota spend proportional to *new* games rather
than to pagination throughput (research.md §6).

Each hourly cycle processes newly-scraped games *and* backfills these gaps for games already
in the catalog (FR-023), so a mid-pipeline failure (e.g. LLM timeout after the game row is
written) is recovered on a later run instead of being permanently mistaken for completed work.
`enrichment_attempts` bounds retries; `PlaythroughTakeaway` and `ReviewSummary` rows are
created lazily, once, by whichever run first finds the output missing (FR-010) — never
regenerated once they exist (FR-024), never version-tracked.
