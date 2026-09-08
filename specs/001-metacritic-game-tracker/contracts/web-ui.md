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

## Monitoring (US5, optional scope) — basic auth required (FR-022)

Protected by HTTP Basic Auth against `MONITORING_USERNAME` / `MONITORING_PASSWORD`
(`.env`). `401` with `WWW-Authenticate` challenge if missing/wrong credentials.

### `GET /monitoring`

Renders current pipeline status: latest `pipeline_runs` rows, worker state, processed
counts (FR-019).

### `GET /monitoring/stream`

Server-Sent Events stream (`text/event-stream`) pushing status updates as
`pipeline_runs` rows change, so `/monitoring` updates without a manual refresh (FR-019,
research.md §2).

### `POST /monitoring/run`

Triggers `IngestGamesUseCase` immediately, outside the hourly schedule (FR-020). Returns
`202 Accepted` with the new `pipeline_runs.id`; `409 Conflict` if a run is already in
progress (edge case: no overlapping runs).
