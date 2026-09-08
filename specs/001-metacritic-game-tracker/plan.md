# Implementation Plan: Metacritic Game Tracker

**Branch**: `001-metacritic-game-tracker` | **Date**: 2026-09-08 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/001-metacritic-game-tracker/spec.md`

## Summary

Build a service that scrapes Metacritic's Games section once per hour (20 new games per
run, "New Releases" first each day then paginated "See All / Newest"), stores/updates a
catalog with per-platform scores, developer/description/video, and critic/user review
summaries, and serves it through a web UI with list/card views, platform filter, title
search, rating sort, and similar-games (from Metacritic's own "Related Games", intersected
with the local catalog). Optional stretch scope: YouTube playthrough takeaway per game, and
a live-monitoring + manual-trigger view behind operator auth. Technical approach: a single
Python service (FastAPI + server-rendered templates) with a DDD layering already scaffolded
(`domain` / `application` / `infrastructure` / `shared`), PostgreSQL for storage, an
in-process hourly scheduler, and raw versioned SQL migrations (already started under
`sql/migrations/`).

## Technical Context

**Language/Version**: Python 3.11+ (pinned 3.11.13 via `.python-version`)

**Primary Dependencies**: FastAPI + Jinja2 (server-rendered web UI), SQLAlchemy 2.0 (async)
+ asyncpg (persistence), httpx (outbound HTTP to Metacritic/YouTube/LLM), selectolax
(HTML parsing), pydantic / pydantic-settings (config + LLM response validation)

**Storage**: PostgreSQL 16, versioned raw SQL migrations under `sql/migrations/`
(`000_meta.sql`, `001_pipeline.sql`, `002_llm_calls.sql` already exist; domain tables added
in this feature — see `data-model.md`)

**Testing**: pytest + pytest-asyncio; deterministic code (HTML parsing, dedup/upsert logic,
source-selection rules, similar-games intersection) tested directly with fixture HTML/data;
`AsyncMock` reserved for the DB session and external HTTP clients (Metacritic, YouTube, LLM)

**Target Platform**: Linux container (Podman), single service exposing a browser-facing web
UI on port 8000

**Project Type**: Single web service (existing `metacritic_game_tracker/` package; no
separate frontend project — server-rendered HTML, no SPA build step)

**Performance Goals**: Catalog list/search/filter/sort responds in well under 1s server-side
for a catalog in the low thousands of games (SC-001's 10s budget is almost entirely human
search-typing time). One hourly ingestion run (20 games: scrape + upsert + review
summarization) completes in well under the 1-hour window between runs, leaving headroom for
LLM latency and optional playthrough enrichment.

**Constraints**: Metacritic scraping MUST be rate-limited (delay between requests) to avoid
hammering the source site — not stated in the brief but required for the service to keep
working at all. Monitoring view + manual-trigger control sit behind single-operator
basic auth (Constitution: Security & Data Handling); the public catalog has no auth.

**Scale/Scope**: ~20 games/hour ingested (~480/day); single or few concurrent web visitors
(mini-project, not a public-traffic service).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Check | Result |
|---|---|---|
| I. Test-First | Tasks generated in `/speckit-tasks` MUST include a "Tests for User Story N" block per story (written first, failing, per Constitution Principle I — not optional for this project) | PASS (constitution overrides the tasks-template's default "tests optional" framing) |
| II. Layered Architecture | Structure below keeps `domain`/`shared` dependency-free, `infrastructure` depending only on them, `application` orchestrating all three — matches existing `tach.toml` | PASS |
| III. Python/Poetry/Podman | Uses the already-scaffolded Poetry project and `docker-compose.yml`; no new runtime/tooling introduced | PASS |
| IV. Quality Gate | No change to the gate; tasks.md will end with a task running `ruff check .` / `tach check` / `pytest tests/ -q` | PASS |
| V. Explicit-Consent Commits | Plan/tasks introduce no automatic commit behavior | PASS |
| Security & Data Handling | Review text/transcripts routed through `shared.guardrail`; web output through `shared.sanitizer`; `llm_calls` table (already migrated) carries required cost columns; monitoring/force-run behind basic auth per FR-022 | PASS |

No violations — Complexity Tracking table intentionally omitted.

## Project Structure

### Documentation (this feature)

```text
specs/001-metacritic-game-tracker/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md         # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
└── tasks.md             # Phase 2 output (/speckit-tasks — not created here)
```

### Source Code (repository root)

```text
metacritic_game_tracker/
├── domain/
│   ├── models.py        # Game, PlatformScore, ReviewSummary, PlaythroughTakeaway — pure dataclasses
│   └── rules.py          # daily source selection, dedup key, similar-games intersection
├── application/
│   ├── ingest.py          # IngestGamesUseCase: select source → scrape → upsert → record pipeline_runs
│   ├── summarize.py       # GenerateReviewSummariesUseCase (critic + user, separate LLM calls)
│   ├── playthrough.py    # FindPlaythroughTakeawayUseCase (US4, optional scope)
│   └── catalog.py         # ListGames / GetGameDetail / search+filter+sort (US1-3)
├── infrastructure/
│   ├── db/
│   │   ├── models.py       # SQLAlchemy ORM models
│   │   ├── session.py       # async engine/sessionmaker
│   │   └── repositories.py # GameRepository: upsert, query/filter/search/sort, related-games lookup
│   ├── scraper/
│   │   ├── metacritic_client.py  # httpx: New Releases / See All page N / game detail pages
│   │   └── parser.py             # selectolax: HTML → domain fields incl. Related Games list
│   ├── llm/
│   │   └── review_summarizer.py  # uses shared.llm_config routes, writes llm_calls rows
│   ├── youtube/
│   │   └── playthrough_finder.py # US4: search + pick most-viewed + transcript (optional scope)
│   ├── scheduler/
│   │   └── hourly_job.py         # triggers IngestGamesUseCase hourly, records pipeline_runs
│   └── web/
│       ├── app.py                 # FastAPI app factory
│       ├── routes_catalog.py       # US1-3 endpoints
│       ├── routes_monitoring.py    # US5 endpoints, basic-auth protected (optional scope)
│       └── templates/              # list.html, game_card.html, monitoring.html
└── shared/                         # guardrail.py, sanitizer.py, llm_config.py (already exist)

tests/
├── domain/            # rules.py, models.py — pure unit tests
├── application/         # use cases with AsyncMock repositories/clients
├── infrastructure/
│   ├── scraper/         # parser tests against saved fixture HTML, no live HTTP
│   └── db/               # repository tests against a real test DB (or transactional fixture)
└── contract/            # FastAPI TestClient tests for routes_catalog / routes_monitoring
```

**Structure Decision**: Single project, extending the existing scaffolded package —
no separate frontend project. UI is server-rendered (Jinja2) to keep the mini-project
scope small; `routes_monitoring.py` (US5) is the only piece needing live updates and uses
Server-Sent Events rather than pulling in a websocket framework.

## Complexity Tracking

*No Constitution Check violations — table intentionally empty.*
