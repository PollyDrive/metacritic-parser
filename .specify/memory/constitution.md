<!--
Sync Impact Report
- Version change: (unset/template) → 1.0.0
- Modified principles: n/a (initial ratification)
- Added sections: Core Principles (I-V), Security & Data Handling, Development Workflow, Governance
- Removed sections: none
- Follow-up TODOs: none
-->
# Metacritic Game Tracker Constitution

## Core Principles

### I. Test-First (NON-NEGOTIABLE)

TDD is mandatory for every feature and bugfix: a failing test MUST exist before any
production code is written. Cycle is strictly RED → GREEN → REFACTOR — write the test,
watch it fail for the right reason (assertion, not import error), write the minimal
code to pass it, then refactor without changing behavior. No production code is
committed without a test that exercised it first.

**Rationale**: catches regressions in a scraping/LLM pipeline where failures are easy
to miss silently (a parser that "succeeds" against changed HTML, a summary that's
subtly wrong) and where manual re-verification after every change doesn't scale.

### II. Layered Architecture with Enforced Boundaries

The codebase is organized as `domain` → `infrastructure` → `application`, plus a
`shared` layer for cross-cutting concerns. `domain` and `shared` MUST NOT depend on
anything else in the codebase. `infrastructure` MUST only depend on `domain` and
`shared`. `application` MAY depend on all three. No layer may import "backwards"
(e.g., `domain` importing `infrastructure`). These boundaries are enforced
mechanically via `tach check`, not by convention or review alone.

**Rationale**: keeps scraping/LLM/DB adapters (infrastructure) swappable and testable
in isolation from business rules (domain), and prevents the layering from silently
eroding as the codebase grows past a single contributor's memory of the rules.

### III. Python 3.11+ / Poetry / Podman-Only Infrastructure

The project targets Python 3.11 or newer, with Poetry as the sole dependency and
environment manager (`pyproject.toml` / `poetry.lock` are the source of truth — no
parallel `requirements.txt`). All runtime infrastructure (database, application
container) MUST run through Podman via `docker-compose.yml` / `podman compose`; no
service is stood up by hand outside that definition. Local development (tests, lint)
runs directly via `poetry run` against infrastructure started the same way.

**Rationale**: one dependency manager and one container runtime eliminates
"works on my machine" drift between contributors and between local/CI/production.

### IV. Quality Gate Before Done (NON-NEGOTIABLE)

Work is not considered complete until `ruff check .`, `tach check`, and
`pytest tests/ -q` all pass with zero failures. This gate applies to every change,
not only ones touching "risky" code — there is no category of change exempt from it.

**Rationale**: a partially-green gate is indistinguishable from a broken one once
skipped once; the rule stays simple and absolute rather than judgment-dependent.

### V. Explicit-Consent Commits

Git commits are made only when the user explicitly asks for one in that moment.
Completing a task, passing the quality gate, or finishing a session are not by
themselves authorization to commit.

**Rationale**: keeps the user in control of what enters project history and when,
independent of how confident the agent is that the work is finished.

## Security & Data Handling

Third-party text passed into an LLM (scraped reviews, playthrough transcripts) MUST
be run through `metacritic_game_tracker.shared.guardrail.sanitize_input()` first.
Any text surfaced back through the web interface MUST be run through
`metacritic_game_tracker.shared.sanitizer.mask_secrets()` first. Secrets (API keys,
DB credentials, the monitoring operator password) live only in `.env` / CI variables
and are never hardcoded. Any table persisting LLM calls MUST record
`model`, `input_tokens`, `output_tokens`, `cost_usd`, and `created_at`. The
monitoring view and the manual ingestion-trigger control MUST sit behind operator
authentication (single username/password); the public catalog (browse/search/
filter/sort) MUST NOT require authentication.

## Development Workflow

Standard sequence for any feature or bugfix: consult `specs/<feature>/spec.md` (and
`plan.md`/`tasks.md` once generated) for the requirement, use the `/tdd` workflow to
drive RED → GREEN → REFACTOR for each task, then run the full quality gate (Principle
IV) before reporting the work as done. Deterministic code (HTML parsing, dedup logic,
domain rules) is tested directly, never mocked; `AsyncMock` is reserved for the
database session and external HTTP clients (Metacritic, YouTube, the LLM provider).
Hourly ingestion runs record their outcome in `pipeline_runs`/`pipeline_rejects`
(see `sql/migrations/001_pipeline.sql`) with a reason code for anything rejected,
not just an aggregate count.

## Governance

This constitution supersedes any conflicting convention elsewhere in the repository,
including `CLAUDE.md`, which provides supplementary day-to-day runtime guidance but
MUST NOT contradict the principles here. Amendments require the change to be written
into this file with an updated Sync Impact Report and a version bump: MAJOR for a
backward-incompatible principle removal or redefinition, MINOR for a new principle or
materially expanded section, PATCH for wording/clarification only. Any pull request
or review MUST verify compliance with these principles; deviations require a
documented justification (see `plan.md`'s Complexity Tracking table) rather than
silent exceptions.

**Version**: 1.0.0 | **Ratified**: 2026-09-08 | **Last Amended**: 2026-09-08
