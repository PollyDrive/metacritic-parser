# Contracts: Independent Pipeline Enable Switches

Delta only — extends spec 001's `contracts/web-ui.md`. No new endpoint; one existing endpoint's
observable behavior changes.

## `POST /monitoring/run` — behavior change

**Before**: `kind=playthrough` returned `409 {"detail": "Playthrough enrichment is disabled"}`
when `enrichment.playthrough_enabled` was `false`.

**After**: `kind=playthrough` behaves exactly like every other `kind` — it always enqueues a
`run_requests` row and returns `202` (subject only to the existing "another pipeline is already
running" / "a request of this kind is already pending" `409`s, unchanged). Per spec.md FR-009, a
manual, operator-initiated run proceeds regardless of that pipeline's own enable switch.

The same "manual always proceeds" rule now applies uniformly to `kind=ingest`,
`kind=review_refresh`, and `kind=playthrough` alike — `ingest` already worked this way; this
feature makes `playthrough` consistent with it and establishes the same guarantee for
`review_refresh`ing (no `enrichment.review_summary_enabled`-based rejection is introduced for the
manual path).

## `GET /monitoring/config` — no endpoint change

Renders every `runtime_config` key generically (spec 001, unchanged template/route). The new
`enrichment.review_summary_enabled` key appears automatically once seeded — no route or template
change needed, same as every prior key.
