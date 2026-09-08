# Phase 1 Data Model: Metacritic Game Tracker

Entities derived from `spec.md`'s Key Entities section, refined with concrete fields/types.
Tables not listed here (`meta.llm_model_costs`, `pipeline_runs`, `pipeline_rejects`,
`pipeline_findings`, `llm_calls`) already exist under `sql/migrations/000-002` and are
reused as-is by this feature.

## Game

Core catalog entity. One row per Metacritic game page, regardless of how many platforms
it's released on.

| Field | Type | Notes |
|---|---|---|
| `id` | serial PK | |
| `metacritic_slug` | text, unique | Metacritic's own URL slug — natural dedup key (FR-007) |
| `title` | text, not null | |
| `cover_image_url` | text | |
| `developer` | text | |
| `description` | text | |
| `video_url` | text, nullable | not every game has one |
| `related_games_raw` | jsonb, not null default `[]` | scraped "Related Games" list (slugs/titles) as-is; FR-016's similar-games intersection reads this, not a stored relationship (see research.md §4) |
| `first_seen_at` | timestamptz, not null default now() | |
| `last_updated_at` | timestamptz, not null default now() | bumped on every re-crawl (FR-007) |

**Validation**: `metacritic_slug` required and unique — this is what makes an ingestion run
an upsert instead of a duplicate insert (FR-007). `title` required.

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
| `generated_at` | timestamptz, not null default now() | regenerated every re-crawl (FR-010) |
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
`source` set to `'new_releases'` or `'see_all_newest'`.

## Relationships

```text
Game 1──* PlatformScore
Game 1──0..2 ReviewSummary   (audience='critic' | 'user')
Game 1──0..1 PlaythroughTakeaway   (optional scope)
Game.related_games_raw ──(intersected at read time against Game.metacritic_slug)──> "similar games"
ReviewSummary / PlaythroughTakeaway ──*──1 llm_calls   (cost/traceability)
```

## State Transitions

Games have no explicit status field — presence in the table plus `last_updated_at` is
sufficient (a game is either "in the catalog" or not; there's no draft/published split
per the spec). `PlaythroughTakeaway` and `ReviewSummary` rows are created lazily and
overwritten in place on regeneration (FR-010), never versioned/history-tracked.
