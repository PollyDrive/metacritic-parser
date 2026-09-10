# Phase 0 Research: Independent Pipeline Enable Switches

## 1. Naming and placement of the new review-summary switch

**Decision**: `enrichment.review_summary_enabled` (boolean, default `true`), seeded into the
existing `runtime_config` table.

**Rationale**: The sibling feature's own playthrough switch is named
`enrichment.playthrough_enabled` — a hard on/off master flag under the `enrichment.*` namespace.
`reviews.growth_threshold`/`reviews.critic_sample_size`/`reviews.user_sample_size` are all
*tuning* knobs for a pipeline that's otherwise always-on, not on/off switches — mixing this new
hard-off flag into that namespace would blur that distinction. `enrichment.review_summary_enabled`
groups it with the one other master switch this system already has, both semantically and in the
settings UI (`config_labels.py` already orders keys by namespace).

**Alternatives considered**: `reviews.enabled` — rejected for the namespace-mixing reason above.

## 2. Where "off" must take effect for review-summary generation

**Decision**: Gate exactly one call site — the inline enrichment call in
`application/ingest.py`'s `_try_enrich` (called once per newly-admitted-or-incomplete game during
every ingest run) — and one dispatch decision — `scripts/run_scheduler.py`'s worker loop's
scheduled-review-refresh branch.

**Rationale**: Every review-summary code path funnels through `ReviewEnrichmentUseCase.run()`,
called from exactly these two places. Gating the two call sites gates the whole pipeline; no
change inside `ReviewEnrichmentUseCase` itself is needed, since spec.md FR-010 already requires
skipping the userscore-refresh side effect too — that side effect is *inside* `run()`, so simply
never calling `run()` satisfies FR-003 and FR-010 in one move (research.md of the sibling feature
already established that the stats sweep and any summarization live inside this one method).

**Alternatives considered**: A flag inside `ReviewEnrichmentUseCase.run()` itself, checked before
the stats sweep — rejected as an unnecessary third call site to update (and a third place a future
change could forget to check) when both existing callers can simply not invoke it at all.

## 3. Manual-trigger override — a real inconsistency found in the existing code

**Decision**: Move the enable-check for both `review_refresh` and `playthrough` out of
`scripts/run_scheduler.py`'s `_run_review_refresh`/`_run_playthrough` functions and into
`main()`'s own dispatch condition, exactly mirroring how `infrastructure/scheduler/tick.py`'s
`decide()` already lets a pending manual `run_requests` row bypass `ingest.enabled` (the pending
check runs *before* the enabled check, so a manual ingest trigger always proceeds regardless of
the switch).

**Rationale — this surfaced a genuine, pre-existing bug during planning, not something new this
feature introduces**: `_run_playthrough` currently checks `enrichment.playthrough_enabled` *inside
itself*, unconditionally — so even a manual, explicit `kind == "playthrough"` trigger from
`POST /monitoring/run` silently does nothing (returns early, no `pipeline_runs` row) when the
switch is off. Separately, `routes_monitoring.py`'s `trigger_run` handler *also* rejects a manual
playthrough trigger outright with `409` when the switch is off
(`tests/contract/test_monitoring_run.py::test_post_run_rejects_playthrough_when_the_feature_is_disabled`).
Both of these contradict spec.md FR-009 ("An operator-initiated, out-of-schedule run... MUST
proceed regardless of that pipeline's own enable setting") once FR-009 is read as the single rule
that should govern *all three* pipelines consistently — today only `ingest`'s manual trigger
actually behaves that way. Fixing this is in scope for this feature, not a separate bug: FR-009
is this feature's own requirement, spec-writing surfaced that playthrough's current behavior
violates it, and the fix is a small, mechanical move of an existing check rather than new
mechanism.

Concretely: `main()`'s dispatch condition becomes
`kind == "review_refresh" or (kind == "scheduled" and enrichment.review_summary_enabled and stage_due(...))`
and `kind == "playthrough" or (kind == "scheduled" and enrichment.playthrough_enabled and stage_due(...))`
— the enable check only ever gates the *scheduled* branch of the `or`; a manual `kind` always
short-circuits it, same as `decide()` already does for ingest. The 409 block in
`routes_monitoring.py`'s `trigger_run` for `kind == "playthrough"` is removed outright — a manual
trigger no longer needs to pre-check the switch at all, since the worker will run it unconditionally
once it dequeues the request.

**Alternatives considered**: Leaving the internal checks in `_run_playthrough`/adding an
equivalent one to `_run_review_refresh`, and only fixing the `409` in `routes_monitoring.py` —
rejected because the internal check alone still silently no-ops a manual trigger (no pipeline_runs
row, no visible outcome in `/monitoring`) even without the `409`, which is a worse operator
experience than either "runs" or "clearly rejected."

## 4. Whether `detail_backfill` shares the discovery switch

**Decision**: No — `scripts/run_scheduler.py`'s `_run_detail_backfill` keeps running on its own
existing cadence regardless of the new discovery switch's state, unchanged by this feature.

**Rationale**: spec.md's own FR-002 says turning discovery off must "leave already-cataloged games
and their enrichment untouched by this setting." Detail-field backfill (recovering a missing
description/developer/cover image for a game Gate B already admitted, per spec 001 FR-028) is
exactly that: repair work on already-cataloged games, not discovery of new ones. spec.md's
Assumptions section, as first drafted, said the opposite (that detail-backfill "shares" discovery's
switch) — that was an oversight that directly contradicts FR-002's own explicit text once the two
were compared side by side during planning; FR-002 (a numbered, testable requirement) governs over
the Assumptions bullet (background context), so spec.md's Assumptions section is corrected here to
match FR-002 rather than the other way around.

**Alternatives considered**: Gating `_run_detail_backfill` behind the discovery switch as
originally assumed — rejected once it was clear this directly contradicts FR-002.

## 5. Contract impact

**Decision**: `POST /monitoring/run?kind=playthrough` changes observable behavior: it no longer
returns `409` when `enrichment.playthrough_enabled` is `false` — it now always enqueues the
request (`202`), same as every other `kind`. This is the only externally-visible contract change;
`GET /monitoring/config` gains one more row (the new key) automatically, matching how every prior
`runtime_config` key already surfaces there with no template change needed.

**Alternatives considered**: None — this follows directly from decision 3 above.
