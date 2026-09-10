# Quickstart: Independent Pipeline Enable Switches

Validation guide — proves the feature works end-to-end once implemented. Builds on spec
001/002's own quickstarts for infrastructure/migrations/running `app` + `worker`; this guide only
covers what's new.

## Prerequisites

- Sibling features' quickstart steps done: infrastructure up, migrations applied (including this
  feature's new migration seeding `enrichment.review_summary_enabled`), `app` + `worker` running.
- At least one game already cataloged with both review summaries generated.

## 1. Confirm review-summary generation stops completely when off

1. In `/monitoring/config`, turn `enrichment.review_summary_enabled` off.
2. Trigger a manual ingest run bringing in at least one new game.
3. Confirm the new game is cataloged (title, cover, scores) but has **no** critic/user summary.
4. Trigger a manual `review_refresh` run covering a game whose review count has grown well past
   its recorded total.
5. Confirm that game's existing summary and recorded count are unchanged, no new `llm_calls` row
   was written, and its displayed userscore did not refresh either (FR-010).

**Pass condition**: matches spec.md FR-003, FR-004, FR-010; User Story 1, Acceptance Scenarios 1-2.

## 2. Confirm summary generation resumes once turned back on

1. Turn `enrichment.review_summary_enabled` back on.
2. Trigger ingest and review-refresh again.
3. Confirm the game from Step 1 above now gets a summary (or refreshed summary) with no restart
   needed.

**Pass condition**: matches User Story 1, Acceptance Scenario 3; SC-004.

## 3. Confirm discovery off does not pause summaries or playthroughs

1. Turn `ingest.enabled` off; leave `enrichment.review_summary_enabled` and
   `enrichment.playthrough_enabled` on.
2. Wait for (or manually trigger) `review_refresh` and `playthrough` passes.
3. Confirm the catalog's game count does not grow, while an existing game's summary still
   refreshes on growth and an existing game still gets a playthrough takeaway searched for.

**Pass condition**: matches spec.md FR-002, FR-006, FR-007; User Story 2, all scenarios; SC-002.

## 4. Confirm playthrough off does not block its own manual trigger

1. Turn `enrichment.playthrough_enabled` off.
2. Call `POST /monitoring/run?kind=playthrough` directly (or via the operator console).
3. Confirm it returns `202`, not `409` — and that the worker actually runs it (a
   `pipeline_runs` row with `stage='playthrough'` appears), even though the scheduled cadence
   would have skipped it.
4. Confirm no *scheduled* playthrough tick runs while the switch stays off.

**Pass condition**: matches spec.md FR-009; contracts/web-ui.md's documented behavior change;
User Story 3, Acceptance Scenarios 1-2.

## 5. Confirm all three off means zero outbound requests

1. Turn all three switches off.
2. Let several worker ticks pass.
3. Confirm no new `pipeline_runs` rows appear for `ingest`, `review_refresh`, or `playthrough`
   (scheduled), and the existing catalog remains fully browsable via the public site.

**Pass condition**: matches spec.md SC-005.

## 6. Full quality gate (Constitution Principle IV)

```bash
poetry run ruff check .
poetry run tach check
poetry run pytest tests/ -q
```

All three must be clean before the feature is considered done.
