# Contracts: Web Interface

Server-rendered HTTP endpoints exposed by `infrastructure/web/app.py`. No separate JSON
API is contracted for this feature — the HTML endpoints below ARE the interface (per
research.md §2, no SPA/frontend project).

## Public catalog (US1-3) — no auth

### `GET /games`

List view. Query params (all optional, all combinable):

| Param | Type | Behavior |
|---|---|---|
| `platform` | string | FR-013 — filter to games with a `PlatformScore.platform` match |
| `q` | string | FR-014 — case-insensitive substring match on `Game.title` |
| `sort` | `rating` \| unset | FR-015 — order by best available score (metascore, falling back to userscore*10) descending |

Response: HTML list, each row showing title, cover image, platform(s), score(s) (FR-011).
Empty catalog → empty-state HTML, not an error.

### `GET /games/{id}`

Detail card (FR-012). 404 (HTML) if `id` doesn't exist. Renders: title, cover, developer,
description, video link, per-platform Metascore/Userscore, critic review summary, user
review summary, similar games section (FR-016/017, empty section if none qualify per Edge
Cases), playthrough takeaway if present (US4, optional scope — section omitted entirely
when absent, not shown empty).

## Operator console (US5) — basic auth required (FR-022, FR-026)

Protected by HTTP Basic Auth against `MONITORING_USERNAME` / `MONITORING_PASSWORD`
(`.env`). `401` with `WWW-Authenticate` challenge if missing/wrong credentials.

### `GET /monitoring`

Renders current pipeline status (FR-019). Beyond the latest-run-per-pipeline summary, the
response includes:

- **Run history**: the last 20 `pipeline_runs` rows across all stages (`ingest`, `review_refresh`,
  `playthrough`, `detail_backfill`), each expandable (accordion) to show its own
  `GameActivityEvent` rows and `pipeline_rejects` rows, scoped by `run_id`.
- **Error log**: every `pipeline_rejects` row and every `enrichment_attempts` row with a non-null
  `last_error`, merged and sorted newest-first — the operator-facing view of everything that
  didn't complete cleanly, not bounded to the current run.
- **Playthrough coverage**: `games_with_playthrough / total_games`, shown against the
  `playthrough` pipeline's summary row (US ask: "how many games have a playthrough at all").
- **YouTube call count per run**: for `playthrough`-stage runs, a count of API calls actually
  spent (derived from `playthrough_generated` events plus `no_candidate_video`/`no_transcript`
  rejects, both only reachable past the daily-budget check) — distinguishes "ran and found
  nothing" from "budget exhausted before it could search."
- **Cross-game activity feed**: every `GameActivityEvent` row, grouped by game, newest-first —
  independent of the run-history accordion above, this is "what's happened to this game
  recently" rather than "what happened in this run."

### `GET /monitoring/stream`

Server-Sent Events stream (`text/event-stream`) pushing status updates as
`pipeline_runs` rows change, so `/monitoring` updates without a manual refresh (FR-019,
research.md §2).

### `POST /monitoring/run`

Requests an immediate ingestion run, outside the hourly schedule (FR-020). The web tier does
**not** execute the run — it inserts a `run_requests` row that the worker process consumes on
its next poll (research.md §3). Returns `202 Accepted` with the `run_requests.id`;
`409 Conflict` if an `ingest` run is currently `running` or an unconsumed request already
exists (edge case: no overlapping runs). The `/monitoring/stream` SSE feed is how the caller
observes the run actually starting.

A manual run bypasses the active-hours window and the `ingest.enabled` switch — it is an
explicit human instruction, not a scheduled tick.

### `GET /monitoring/config`

Settings page (FR-025). Renders every `runtime_config` key with its current value, permitted
range, description, and who last changed it. Secrets are not present in this table and are
never rendered here (FR-026).

### `POST /monitoring/config`

Saves changed settings. Each submitted value is validated **server-side** against its
`value_type` and `min_value`/`max_value` before being persisted; out-of-range or wrong-typed
input returns `422` with per-field messages and leaves every stored value untouched (all-or-
nothing, so a partial save can't leave the pipeline in a half-retuned state). On success:
`303 See Other` back to `GET /monitoring/config`, with `updated_at`/`updated_by` recorded per
changed key. Changes take effect on the worker's next run — no restart (FR-025).

Rejected explicitly: any key not in the seeded `runtime_config` set. The endpoint does not
create new keys, so it cannot be used to write arbitrary rows.
