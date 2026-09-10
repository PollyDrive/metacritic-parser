# Phase 1 Data Model: Independent Pipeline Enable Switches

No new tables. Extends the existing `runtime_config` mechanism (`sql/migrations/005_runtime_config.sql`,
spec 001) with one new seeded key — the same mechanism `ingest.enabled` and
`enrichment.playthrough_enabled` already use.

## RuntimeConfig (new seeded key)

| Key | Default | Bounds | Meaning |
|---|---|---|---|
| `enrichment.review_summary_enabled` | `true` | — | Master switch for review-summary generation (FR-003/FR-004/FR-010) — both the inline call during ingest and the scheduled review-refresh pass. |

**Validation**: identical bounds-checking mechanism as every other `runtime_config` key
(`infrastructure/config/runtime.py`, already built) — a boolean key, same shape as
`ingest.enabled`/`enrichment.playthrough_enabled`.

## Relationships

```text
runtime_config.ingest.enabled                     ──> gates scheduled new-game discovery (existing, unchanged)
runtime_config.enrichment.review_summary_enabled  ──> gates scheduled review-summary generation (new)
runtime_config.enrichment.playthrough_enabled     ──> gates scheduled playthrough search (existing; manual-trigger bypass fixed)
```

Each of the three is read independently, at the point `scripts/run_scheduler.py`'s worker loop
decides whether to dispatch that pipeline's *scheduled* run — never inside the pipeline's own
use case, and never checked at all for a manual, operator-triggered run of that same pipeline
(FR-009).

## State Transitions

No new entity, no new state machine — this feature only adds a read at three existing decision
points (two already existing for `ingest.enabled`/`enrichment.playthrough_enabled`, one new for
`enrichment.review_summary_enabled`) and removes one incorrect blocking check
(`routes_monitoring.py`'s manual-playthrough-trigger `409`, research.md §3).
