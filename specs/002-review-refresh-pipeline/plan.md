# Implementation Plan: Review Refresh Pipeline

**Branch**: `002-review-refresh-pipeline` | **Date**: 2026-09-09 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/002-review-refresh-pipeline/spec.md`

## Summary

Split review-summary maintenance into two pipelines. The existing hourly ingest pipeline
(spec 001, unchanged in behavior) keeps discovering and cataloging new games, and now also
records the review count each first-time summary was generated at. A new, independently-paced
refresh pass revisits already-cataloged games on an aggressively decaying schedule (every 3
a single cheap no-LLM fetch per due game to read its current review counts, and only calling the
LLM to regenerate a summary — per audience, independently — when growth over the recorded count
clears a configurable percentage threshold (default 25%). Technical approach: extend the two
tables and the `runtime_config` mechanism spec 001 already built.

*Update (Architecture Review 1)*: To avoid architectural conflicts and duplicate code between ingestion and refresh pipelines, the fetching and summarization logic was extracted into `ReviewEnrichmentUseCase` (in `application/enrichment.py`). The existing `BackfillEnrichmentUseCase` and `run_scheduler.py` worker tick were updated to handle decayed TTL refreshes natively, reusing the same politeness delays and constraints as standard ingestion.

## Technical Context

**Language/Version**: Python 3.11+ (matches spec 001; same project, no new runtime)

**Primary Dependencies**: Same as spec 001 — FastAPI/Jinja2, SQLAlchemy 2.0 async + asyncpg,
httpx, selectolax, `shared.llm_config` routes. No new dependency introduced by this feature.

**Storage**: PostgreSQL 16, versioned raw SQL migrations under `sql/migrations/` — this feature
adds `007_review_refresh.sql` (extends `games` and `review_summaries`, seeds new
`runtime_config` keys; see `data-model.md`).

**Testing**: pytest + pytest-asyncio, same conventions as spec 001 — the two new count-extraction
functions are deterministic and tested directly against the existing saved fixture HTML
(`tests/infrastructure/scraper/fixtures/`), no live HTTP; `AsyncMock` reserved for the DB
session and the LLM/HTTP clients.

**Target Platform**: Same Linux container / two-process (`app` + `worker`) topology as spec 001 —
this feature only adds work to the existing `worker` process, no new process or port.

**Project Type**: Single web service (existing `metacritic_game_tracker/` package) — extends it,
does not add a project.

**Performance Goals**: A refresh-pass recheck (count-only, no LLM) completes in one HTTP fetch
per due game; capped at `review_refresh.games_per_run` (default 20) per worker tick, so a full
pass costs at most that many fetches — small relative to a full ingest run's per-game cost
(research.md §1, §5).

**Constraints**: The refresh pass MUST NOT delay or block the ingest pipeline's discovery of
new games (spec.md FR-003) — addressed by running as a third, independently-capped step in the
same tick rather than a blocking dependency (research.md §5). All operator-tunable values
(decay tiers, cutoff age, growth threshold, per-run cap) live in `runtime_config`, matching
spec 001's existing pattern (research.md §4).

**Scale/Scope**: Bounded by the existing catalog size (~480 games/day at spec 001's steady
state); the refresh pass only ever considers already-cataloged games younger than
`review_refresh.max_age_weeks` (default 4 weeks), so its candidate set is a small, aging-out
rolling window, not the whole catalog.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Check | Result |
|---|---|---|
| I. Test-First | Tasks generated in `/speckit-tasks` MUST include a failing-test-first block per task (count extraction, due-selection query, growth-check logic, use-case orchestration) | PASS |
| II. Layered Architecture | New pure logic (decay-tier resolution, growth-threshold check) goes in `domain/rules.py`; new count-extraction goes in `infrastructure/scraper/parser.py`; new orchestration goes in `application/review_refresh.py` — same layering `tach.toml` already enforces, no new dependency direction | PASS |
| III. Python/Poetry/Podman | No new dependency, no new runtime component | PASS |
| IV. Quality Gate | `ruff check .` / `tach check` / `pytest tests/ -q` unchanged, still the done-bar | PASS |
| V. Explicit-Consent Commits | Plan/tasks introduce no automatic commit behavior | PASS |
| Security & Data Handling | Review text still routed through `shared.guardrail.sanitize_input()` before the LLM (same summarizer path as spec 001); regenerated `llm_calls` rows still carry `model`/`input_tokens`/`output_tokens`/`cost_usd`/`created_at`; no new web-facing surface, so no new auth surface either | PASS |

No violations — Complexity Tracking table intentionally omitted.

## Project Structure

### Documentation (this feature)

```text
specs/002-review-refresh-pipeline/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
└── tasks.md             # Phase 2 output (/speckit-tasks — not created here)
```

No `contracts/` directory: this feature adds no new external interface. The one observable
surface change — `pipeline_runs.stage` gaining a `'review_refresh'` value — is already rendered
generically by the existing `/monitoring` page (spec 001's `routes_monitoring.py` /
`monitoring.html` iterate `pipeline_runs` rows without switching on `stage`), so no contract or
template change is needed there either.

```text
metacritic_game_tracker/
├── domain/
│   └── rules.py                   # + calculate_next_refresh()
├── application/
│   └── enrichment.py              # NEW: ReviewEnrichmentUseCase (consolidates ingest & refresh logic)
├── infrastructure/
│   └── db/
│       └── repositories.py        # + GameRepository support for next_refresh_at
└── shared/guardrail.py            # reused as-is

scripts/
└── run_scheduler.py                # worker tick uses ReviewEnrichmentUseCase for backfill and decayed TTL refreshes

sql/migrations/
└── 005_release_date_and_refresh.sql # games.release_date, games.next_refresh_at

tests/
├── domain/
│   └── test_rules.py               # + calculate_next_refresh logic
└── application/
    └── test_backfill.py            # + testing decayed TTL integration in backfill
```

**Structure Decision**: No new project, process, or port. `ReviewEnrichmentUseCase` consolidates the logic to fetch reviews and summarize them. It is invoked natively by the existing `BackfillEnrichmentUseCase` in `scripts/run_scheduler.py`, which now selects games whose `next_refresh_at` has expired. This prevents architectural duplication and ensures politeness delays via `MetacriticClient` are respected.

## Complexity Tracking

*No Constitution Check violations — table intentionally empty.*
