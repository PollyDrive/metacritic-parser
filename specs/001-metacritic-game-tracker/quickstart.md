# Quickstart: Metacritic Game Tracker

Validation guide — proves the feature works end-to-end once implemented. Not a spec of
behavior (see `spec.md`) or of internals (see `data-model.md` / `contracts/`).

## Prerequisites

- `.env` populated from `.env.example` (DB credentials, `MONITORING_USERNAME`/`PASSWORD`,
  `OPENCODE_API_KEY`, `YOUTUBE_API_KEY` if testing US4)
- `poetry install` already run (see repo root `pyproject.toml`)

## 1. Start infrastructure

```bash
make up          # podman compose up -d — starts Postgres
```

## 2. Apply migrations

```bash
# runner script introduced by this feature's tasks — applies sql/migrations/*.sql in order
poetry run python scripts/migrate.py
```

## 3. Run the service

```bash
poetry run python main.py
```

## 4. Validate User Story 1 — Browse Catalog

1. Trigger one ingestion run manually (see step 6, or wait for the hourly scheduler).
2. Open `http://localhost:8000/games` — expect a list with at least one game, showing
   title, cover image, and platform score(s).
3. Click a game → expect the detail card with developer, description, video link,
   per-platform scores, and both review summaries (critic + user).

**Pass condition**: matches spec.md User Story 1 Acceptance Scenarios 1-2.

## 5. Validate User Story 2 — Filter/Search/Sort

- `http://localhost:8000/games?platform=PS5` → only PS5 games.
- `http://localhost:8000/games?q=<partial title>` → matching games only.
- `http://localhost:8000/games?sort=rating` → ordered by rating.

**Pass condition**: matches spec.md User Story 2 Acceptance Scenarios 1-3.

## 6. Validate User Story 3 — Similar Games

1. Ensure at least two games sharing a "Related Games" entry are in the catalog (may
   require two ingestion runs, since Metacritic controls what's related to what).
2. Open one of their detail cards → expect a "similar games" section listing the other.
3. Click the similar game's name → its own card opens.

**Pass condition**: matches spec.md User Story 3 Acceptance Scenarios 1-2.

## 7. (Optional scope) User Story 4 — Playthrough Takeaway

Run the playthrough enrichment step for a game with a known popular YouTube playthrough;
confirm a takeaway + video link appear on its card. For a game with no findable
playthrough, confirm the card renders normally with no error and no takeaway section.

## 8. (Optional scope) User Story 5 — Monitoring + Manual Trigger

1. Authenticate with `MONITORING_USERNAME`/`PASSWORD` at `http://localhost:8000/monitoring`.
2. Press the manual-run control → `POST /monitoring/run` → expect `202` and the status
   view to update live (via the SSE stream) without a page refresh.

## 9. Full quality gate (Constitution Principle IV)

```bash
poetry run ruff check .
poetry run tach check
poetry run pytest tests/ -q
```

All three must be clean before the feature is considered done.
