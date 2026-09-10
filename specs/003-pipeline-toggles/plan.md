# Implementation Plan: Independent Pipeline Enable Switches

**Branch**: `003-pipeline-toggles` | **Date**: 2026-09-10 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/003-pipeline-toggles/spec.md`

## Summary

Add one new operator-tunable master switch, `enrichment.review_summary_enabled`, alongside the
two that already exist (`ingest.enabled`, `enrichment.playthrough_enabled`), so all three
background pipelines — new-game discovery, review-summary generation, playthrough search — can be
turned on or off independently. Wiring the new switch is small (gate the two call sites that
invoke `ReviewEnrichmentUseCase.run()`), but planning surfaced a real, pre-existing inconsistency
in how the two existing switches interact with manual "Run now" triggers: `ingest.enabled` already
lets a manual trigger bypass it, but `enrichment.playthrough_enabled` currently does not (it
silently no-ops a manual playthrough run, and separately returns `409` for the same case at the
HTTP layer). Fixing that inconsistency — so all three switches behave identically for manual
triggers — is this feature's other deliverable, directly required by spec.md FR-009.

## Technical Context

**Language/Version**: Python 3.11+ (matches specs 001/002; same project, no new runtime)

**Primary Dependencies**: Same as specs 001/002 — FastAPI/Jinja2, SQLAlchemy 2.0 async + asyncpg,
`infrastructure/config/runtime.py`'s existing `RuntimeConfig`. No new dependency.

**Storage**: PostgreSQL 16, versioned raw SQL migrations under `sql/migrations/` — this feature
adds one migration seeding a single new `runtime_config` row (see `data-model.md`).

**Testing**: pytest + pytest-asyncio, same conventions as specs 001/002 — `AsyncMock` for the DB
session; the worker-loop dispatch logic is tested directly (mirrors existing
`tests/infrastructure/scheduler/test_tick.py` patterns).

**Target Platform**: Same Linux container / two-process (`app` + `worker`) topology as specs
001/002 — this feature only changes existing worker-tick dispatch logic and one HTTP route; no
new process, port, or template.

**Project Type**: Single web service (existing `metacritic_game_tracker/` package) — extends it.

**Performance Goals**: No change — this feature only adds config reads (already-cheap, per-tick)
and removes one HTTP-layer check; no new I/O pattern.

**Constraints**: Every switch must take effect on the next relevant pipeline run without a
restart (FR-008), matching the existing `runtime_config` re-read-per-run pattern. A manual,
operator-triggered run of any of the three pipelines must proceed regardless of that pipeline's
own switch (FR-009) — this is the constraint that drives where each check is placed (research.md
§3).

**Scale/Scope**: No change to scale — this feature only affects when existing pipelines run, not
how much work each one does per run.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Check | Result |
|---|---|---|
| I. Test-First | Tasks generated in `/speckit-tasks` MUST include a failing-test-first block per task (dispatch-condition logic, inline-enrichment gating, the `trigger_run` behavior change) | PASS |
| II. Layered Architecture | No new dependency direction: the new check lives in `application/ingest.py` (application layer, already imports `infrastructure/config/runtime.py`) and in `scripts/run_scheduler.py` (a thin entry point per CLAUDE.md, already calling into `application`/`infrastructure`) | PASS |
| III. Python/Poetry/Podman | No new dependency, no new runtime component | PASS |
| IV. Quality Gate | `ruff check .` / `tach check` / `pytest tests/ -q` unchanged, still the done-bar | PASS |
| V. Explicit-Consent Commits | Plan/tasks introduce no automatic commit behavior | PASS |
| Security & Data Handling | No new LLM-calling table, no new web-facing surface, no new auth surface; `enrichment.review_summary_enabled` is a plain operational boolean, never a secret | PASS |

No violations — Complexity Tracking table intentionally omitted.

## Project Structure

### Documentation (this feature)

```text
specs/003-pipeline-toggles/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output (delta against spec 001's contracts/web-ui.md)
└── tasks.md             # Phase 2 output (/speckit-tasks — not created here)
```

### Source Code (repository root)

No new files. Every change extends an existing module:

```text
metacritic_game_tracker/
├── application/
│   └── ingest.py                    # _try_enrich: skip the inline ReviewEnrichmentUseCase.run()
│                                     # call entirely when enrichment.review_summary_enabled is false
└── infrastructure/
    └── web/
        └── routes_monitoring.py     # trigger_run: remove the kind=="playthrough" disabled-check
                                      # 409 block (research.md §3) — manual trigger always proceeds

scripts/
└── run_scheduler.py                 # main(): move the enable-check for review_refresh AND
                                      # playthrough out of _run_review_refresh/_run_playthrough
                                      # and into the dispatch condition itself, so only the
                                      # *scheduled* branch is gated — mirrors how decide() already
                                      # lets a pending manual request bypass ingest.enabled

sql/migrations/
└── 013_review_summary_enabled.sql   # seeds enrichment.review_summary_enabled = true

tests/
├── application/
│   └── test_ingest_dedup.py         # + inline enrichment skipped when the switch is off
├── infrastructure/
│   └── scheduler/                   # (no existing test file covers run_scheduler.py's main()
│                                     # dispatch condition directly today — new coverage needed;
│                                     # exact location decided in /speckit-tasks)
└── contract/
    └── test_monitoring_run.py       # replace test_post_run_rejects_playthrough_when_the_
                                      # feature_is_disabled with the opposite: manual trigger
                                      # proceeds (202) regardless of the switch
```

**Structure Decision**: No new project, process, port, or template. This feature is a narrow,
surgical change to three existing files plus one migration — consistent with spec.md's own scope
(a switch, not new pipeline mechanics) and with specs 001/002's established pattern of extending
`runtime_config` rather than introducing new configuration mechanisms.

## Complexity Tracking

*No Constitution Check violations — table intentionally empty.*
