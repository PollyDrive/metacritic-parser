# Tasks: Independent Pipeline Enable Switches

**Input**: Design documents from `/specs/003-pipeline-toggles/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md), [data-model.md](data-model.md), [contracts/web-ui.md](contracts/web-ui.md), [quickstart.md](quickstart.md)

**Tests**: NOT optional — Constitution Principle I ("Test-First, NON-NEGOTIABLE"). The dispatch
decision this feature centers on (manual-vs-scheduled, per-pipeline enable check) is extracted
into a pure function in `infrastructure/scheduler/tick.py` specifically so it's testable —
`scripts/run_scheduler.py`'s `main()` itself stays untested per CLAUDE.md's cron-script exclusion
("тестировать модули отдельно"), same pattern `decide()`/`stage_due()` already established.

**Organization**: Tasks are grouped by user story (P1/P2 from spec.md). Foundational holds the
shared dispatch-decision function both US1 and US3 depend on.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: US1/US2/US3, matching spec.md's priorities

---

## Phase 1: Foundational (Blocking Prerequisites)

**Purpose**: One new config key, and the single dispatch-decision function that fixes FR-009 for
all three pipelines at once (research.md §3) — both user stories that touch scheduling depend on
this being correct.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

### Tests for Foundational Components

> Write these FIRST, confirm they FAIL before implementing (Constitution Principle I)

- [X] T001 [P] Unit tests for a new `dispatch_due(kind, stage_name, enabled, due)` function in
      `infrastructure/scheduler/tick.py`: `kind == stage_name` (a manual trigger) returns `True`
      regardless of `enabled`/`due` (covers the disabled case — FR-009); `kind == "scheduled"`
      returns `True` only when both `enabled` and `due` are `True`, `False` if either is `False`;
      a `kind` naming a *different* stage returns `False` — in
      `tests/infrastructure/scheduler/test_tick.py` (FR-009, research.md §3)

### Implementation for Foundational Components

- [X] T002 Implement `dispatch_due(kind: str, stage_name: str, enabled: bool, due: bool) -> bool`
      in `infrastructure/scheduler/tick.py` as `return kind == stage_name or (kind == "scheduled"
      and enabled and due)` (makes T001 pass)
- [X] T003 [P] Write `sql/migrations/013_review_summary_enabled.sql` seeding
      `enrichment.review_summary_enabled = true` into `runtime_config`, same shape as the
      existing `enrichment.playthrough_enabled` row (data-model.md)
- [X] T004 [P] Add `enrichment.review_summary_enabled` to `EN_LABELS`/`EN_WHY` in
      `infrastructure/web/config_labels.py`, matching the existing entry style for
      `enrichment.playthrough_enabled`

**Checkpoint**: the dispatch decision that governs every scheduled pipeline tick is correct and
tested; the new switch exists and is visible on the settings page.

---

## Phase 2: User Story 1 - Turn Off Review-Summary Generation Only (Priority: P1)

**Goal**: With `enrichment.review_summary_enabled` off, no critic/user summary is generated for
any game, new or existing, and no userscore refresh happens either (FR-010) — while discovery and
playthrough search continue unaffected.

**Independent Test**: With the switch off, run an ingest pass and a review-refresh pass; confirm
neither produces a new/updated summary for any game, while the catalog and playthrough coverage
continue to update.

### Tests for User Story 1

- [X] T005 [P] [US1] Unit test: `IngestGamesUseCase`'s inline enrichment call (`_try_enrich` /
      `ReviewEnrichmentUseCase.run()`) is never invoked for either audience when
      `enrichment.review_summary_enabled` is `false` — even for a brand-new game that would
      otherwise always qualify (FR-003, zero-base case) — extend
      `tests/application/test_ingest_dedup.py` (FR-003, FR-010)
- [X] T006 [P] [US1] Unit test: with `enrichment.review_summary_enabled` `true` (the default),
      inline enrichment still runs exactly as before — a non-regression check alongside T005,
      reusing `tests/application/test_ingest_dedup.py`'s existing
      `test_enrichment_runs_for_a_newly_admitted_game` as the baseline (no new production
      behavior here, just confirming the new gate defaults open)

### Implementation for User Story 1

- [X] T007 [US1] In `application/ingest.py`, read `enrichment.review_summary_enabled` via
      `self._config` once per run and skip the inline `_try_enrich` call entirely for both
      audiences when it's `false` (depends on T003; makes T005/T006 pass)
- [X] T008 [US1] In `scripts/run_scheduler.py`'s `main()`, replace the inline
      `kind == "review_refresh" or (kind == "scheduled" and stage_due(...))` condition with
      `dispatch_due(kind, "review_refresh", await config.get_bool("enrichment.review_summary_enabled"), await stage_due(...))`
      (depends on T002)

**Checkpoint**: User Story 1 independently functional — summary generation demonstrably stops
completely when the switch is off, and resumes with no restart when turned back on.

---

## Phase 3: User Story 2 - Turn Off New-Game Discovery Only (Priority: P2)

**Goal**: With `ingest.enabled` off, the catalog stops growing while review-summary generation
and playthrough search keep working through the existing catalog — already true today; this
story makes the guarantee explicit and tested.

**Independent Test**: With discovery off, confirm the catalog's game count doesn't grow over
several cycles while an existing game's summary still refreshes on growth and playthrough search
still finds takeaways for existing games.

### Tests for User Story 2

- [X] T009 [P] [US2] Unit test: `dispatch_due`'s `review_refresh`/`playthrough` decisions never
      reference `ingest.enabled` — call `dispatch_due("scheduled", "review_refresh",
      enabled=True, due=True)` and `dispatch_due("scheduled", "playthrough", enabled=True,
      due=True)` and confirm both return `True` with no dependency on any ingest-related state
      (the function's signature has no ingest parameter at all — this test documents and locks
      in that guarantee) — `tests/infrastructure/scheduler/test_tick.py` (FR-002, FR-006, FR-007)

### Implementation for User Story 2

No production change anticipated — `application/backfill.py`'s `_games_missing` (review-refresh's
and playthrough's due-selection) has never referenced `ingest.enabled`, and `dispatch_due`
(Foundational) takes each stage's `enabled`/`due` as independent parameters by construction. If
T009 surfaces a gap, address it directly in `infrastructure/scheduler/tick.py`.

**Checkpoint**: User Story 2 independently functional and its independence from the other two
pipelines is now an explicit, tested contract rather than an incidental fact.

---

## Phase 4: User Story 3 - Turn Off Playthrough Search Only (Priority: P2)

**Goal**: With `enrichment.playthrough_enabled` off, no playthrough takeaway is looked up for any
game on the *scheduled* cadence — but, per FR-009, a manual "Run now" for playthrough still
proceeds. Fixes two real, pre-existing violations of that rule (research.md §3).

**Independent Test**: With the switch off, confirm no scheduled playthrough tick runs; confirm
`POST /monitoring/run?kind=playthrough` still returns `202` and the worker actually executes it.

### Tests for User Story 3

- [X] T010 [P] [US3] Contract test: `POST /monitoring/run?kind=playthrough` returns `202` (not
      `409`) when `enrichment.playthrough_enabled` is `false` — replace
      `tests/contract/test_monitoring_run.py::test_post_run_rejects_playthrough_when_the_feature_is_disabled`
      with the opposite assertion (FR-009; contracts/web-ui.md)

### Implementation for User Story 3

- [X] T011 [US3] In `infrastructure/web/routes_monitoring.py`'s `trigger_run`, remove the
      `if kind == "playthrough": ... raise HTTPException(409, "Playthrough enrichment is
      disabled")` block entirely — a manual trigger no longer pre-checks the switch (depends on
      T010; makes T010 pass)
- [X] T012 [US3] In `scripts/run_scheduler.py`'s `_run_playthrough`, remove the internal
      `if not await config.get_bool("enrichment.playthrough_enabled"): return None` check — the
      enable decision now lives entirely in `main()`'s dispatch condition (T013), not inside the
      pipeline function itself, so a manual invocation is never silently no-op'd
- [X] T013 [US3] In `scripts/run_scheduler.py`'s `main()`, replace the inline
      `kind == "playthrough" or (kind == "scheduled" and stage_due(...))` condition with
      `dispatch_due(kind, "playthrough", await config.get_bool("enrichment.playthrough_enabled"), await stage_due(...))`
      (depends on T002, T012)

**Checkpoint**: All three user stories independently functional — every pipeline's manual trigger
now behaves identically regardless of that pipeline's own switch.

---

## Phase 5: Polish

- [X] T014 Walk through quickstart.md's 6 scenarios manually against a running instance
      (`app` + `worker` both up)
- [X] T015 Full quality gate: `poetry run ruff check .`, `poetry run tach check`,
      `poetry run pytest tests/ -q` — all clean (Constitution Principle IV)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Foundational (Phase 1)**: No dependencies — BLOCKS User Stories 1 and 3 (both dispatch through
  `dispatch_due`); User Story 2 only needs T002 to exist for T009's assertion, not any new
  production code
- **User Story 1 (Phase 2)**: Depends on Foundational (T002, T003)
- **User Story 2 (Phase 3)**: Depends on Foundational (T002) only
- **User Story 3 (Phase 4)**: Depends on Foundational (T002)
- **Polish (Phase 5)**: Depends on all three user stories

### Parallel Opportunities

- T001 (Foundational test) stands alone; T003/T004 in parallel with each other and with T001-T002
- T005/T006 (US1 tests) in parallel — same test file, land as one edit if picked up together
- T009 (US2 test) independent of US1/US3 entirely
- T010 (US3 test) independent of US1/US2
- T008 (US1) and T012+T013 (US3) touch the same function in `scripts/run_scheduler.py` — land
  sequentially if picked up in the same session, but neither depends on the other's completion

---

## Implementation Strategy

### MVP First

1. Phase 1 (Foundational) → Phase 2 (User Story 1)
2. **STOP and VALIDATE**: run quickstart.md §1-2 against User Story 1 alone
3. User Story 1 alone closes the one real gap (no way to fully disable summary generation today);
   User Stories 2 and 3 turn existing-but-inconsistent behavior into an explicit, tested contract

### Incremental Delivery

1. Foundational → the shared dispatch decision is correct and tested
2. + User Story 1 → review-summary generation can be fully, verifiably turned off (MVP)
3. + User Story 2 → discovery's independence from the other two is now an explicit contract
4. + User Story 3 → playthrough's manual-trigger inconsistency is fixed; all three pipelines now
   behave identically for manual triggers
5. Polish → quickstart walkthrough, quality gate green
