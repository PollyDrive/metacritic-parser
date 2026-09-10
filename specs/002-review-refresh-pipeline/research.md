# Phase 0 Research: Review Refresh Pipeline

## 1. Where the "current review count, no LLM" comes from

**Decision**: A single fetch of a game's `/user-reviews/` subpage yields both counts needed for
a no-LLM recheck.

**Rationale**: Verified directly against the existing fixtures
(`tests/infrastructure/scraper/fixtures/game_page_elden_ring.html` and
`game_user_reviews_elden_ring.html`) via the already-existing payload resolver:

- The **critic** total is the game-level (not per-platform) `criticScoreSummary.reviewCount`
  block — its `url` is exactly `/game/<slug>/critic-reviews/`, with no `?platform=` query
  string. This aggregate block is present verbatim on *both* the main game page and the
  `/user-reviews/` subpage (a shared scores-summary component), so it does not require a
  separate fetch of the main page.
- The **user** total has no equivalent site-wide aggregate — Metacritic's `/user-reviews/`
  page instead embeds one `userScore`-shaped block *per platform* (e.g.
  `{"score": 8.4, "reviewCount": 24402, "url": ".../user-reviews/?platform=playstation-5"}`).
  The user total for a game is the sum of `reviewCount` across every such block found on that
  one page.

So one HTTP fetch (`/user-reviews/`) per due game is enough to refresh both counts — cheaper
than the up-to-two-page fetch (`/critic-reviews/` + `/user-reviews/`) the initial-ingest
pipeline already does when it *generates* a summary, because a no-LLM recheck never needs the
sampled review quotes those pages also carry, only the count blocks.

**Alternatives considered**: Fetching `/critic-reviews/` and `/user-reviews/` separately for
their respective counts — rejected once the shared aggregate block was found on the
user-reviews page; halves recheck traffic against Metacritic for no loss of accuracy.
Re-fetching and re-parsing the main game page (`get_resolved_game` / `build_parsed_game`,
already used by initial ingest) — rejected: it would silently re-run full-record extraction
(cover image, developer, genres, etc.) as a side effect of what the spec scopes as a
count-only check (spec.md Assumptions: "no new discovery or admission logic changes"), and it
still wouldn't give a user review count.

**Superseded during implementation**: the decision above (sum `reviewCount` across every
platform block for a game-level user total, and use the SSR page's own aggregate for critic)
was replaced once `infrastructure/scraper/review_api.py` was built against Metacritic's
undocumented `backend.metacritic.com` JSON review API. That API exposes an accurate
per-platform review count *and* paginates past the SSR page's fixed 10-review cap, so the
shipped design instead does a cheap per-platform stats sweep (`pick_best_platform`) and tracks
growth against whichever single platform currently has the most reviews for that audience —
not a cross-platform sum. Rationale: reviews are split per platform on Metacritic, so summing
incomparable pools (e.g. a PS5 review base and a wildly different PC one) is less
representative of what a visitor on either platform actually sees than picking the platform
with the deepest, most current review base and summarizing from it (`application/enrichment.py`
module docstring). The SSR-page approach remains as the fallback when the JSON API's shape
breaks. `review_summaries.total_reviews_count`/`sampled_reviews_count`/`source_url`/
`source_platform` (migration 011) replace the originally-planned single
`review_count_at_generation` column to carry this provenance.

## 2. Persisting the count a summary was generated at

**Decision**: Add `review_count_at_generation` directly to the existing `review_summaries` row
(one row already exists per game per audience, unique on `(game_id, audience)`) rather than a
separate snapshot table.

**Rationale**: The spec's "Review Count Snapshot" entity is, in practice, an attribute of the
summary it belongs to — it has no independent lifecycle (it is written exactly when the
summary is written, by either pipeline, and read only alongside that summary to decide whether
the *next* recheck should regenerate it). A new column keeps the one-summary-per-audience
invariant (`UNIQUE (game_id, audience)`) doing double duty instead of introducing a second
table that must be kept in lockstep with the first.

**Alternatives considered**: A separate `review_count_snapshots` table — rejected as
unnecessary indirection for data with no independent identity or query pattern of its own.

## 3. Tracking which games are due for a recheck

**Decision**: Add `reviews_last_checked_at` (nullable timestamp) directly to `games`. `NULL`
means "never checked by the refresh pass" and is always due immediately — no separate
migration or pipeline step needs to populate it at initial-ingest time (spec.md FR-002: the
initial pipeline must not depend on the refresh pipeline, and this keeps the reverse true too).

**Rationale**: `games` already carries `first_seen_at` (the age anchor the decay curve is
measured from, per spec.md's Assumptions) and `last_updated_at`. One more per-game nullable
timestamp is the smallest addition that lets a single indexed query answer "which games are
due": `first_seen_at` gives age-bucket membership, `reviews_last_checked_at` gives recency of
last recheck within that bucket. A `NULL` default means a freshly-cataloged game becomes
eligible for its first recheck the moment the refresh pass next runs, which is correct — it
has never been rechecked by this pipeline, independent of how recently it was cataloged.

**Alternatives considered**: A separate `review_refresh_state` table keyed by `game_id` —
rejected for the same reason as §2: no independent lifecycle, and `games` already holds the
one other timestamp (`first_seen_at`) the due-check needs.

## 4. Decay curve and growth trigger, made concrete

**Decision** (resolved with the user during `/speckit-specify`):

- Age since `first_seen_at` < 1 week → eligible for a recheck every 3 days.
- 1 week ≤ age < 4 weeks → eligible for a recheck every 7 days.
- age ≥ 4 weeks → excluded from the refresh pass entirely (spec.md Edge Cases: no automatic
  reactivation; a later revival, e.g. a remaster, is out of scope for this feature).
- A regeneration triggers when `observed_count > recorded_count * (1 + growth_threshold_pct)`,
  evaluated independently per audience. Default `growth_threshold_pct = 0.25` (25%). A
  `recorded_count` of 0 makes any positive `observed_count` clear the threshold automatically
  (percentage-of-zero is zero, so any growth qualifies) — matches spec.md's zero-base edge
  case without a special-cased branch.

All four values (the two interval tiers, the cutoff age, and the threshold percentage) are
seeded into `runtime_config` (research.md §11 of the sibling feature already established this
pattern) so they're operator-tunable without a deploy, per spec.md FR-010.

## 5. Where this runs relative to the existing worker tick

**Decision**: A third step in the same worker tick that already runs `IngestGamesUseCase` then
`BackfillEnrichmentUseCase` (`scripts/run_scheduler.py`), gated by its own
`review_refresh.enabled` switch and capped by its own `review_refresh.games_per_run`, with its
due-set computed fresh from the DB each tick (mirrors how `BackfillEnrichmentUseCase` already
runs every tick and simply does nothing when its own derived queue is empty — no separate
`tick.decide()`-style schedule gate needed).

**Rationale**: Satisfies spec.md FR-003 ("independent of, and does not delay, [...] discovery
of newly released games") the same way backfill already coexists with ingest today: each step
is bounded by its own row cap, and a stalled or slow step doesn't block the others from running
on the *next* tick — poll interval is seconds, not hours, so a bounded step running long delays
the next step by at most that step's own duration, never compounding. Introducing a second
worker process or a separate polling loop was considered and rejected as unwarranted complexity
for a step that is, by construction (small `games_per_run` cap, single cheap HTTP fetch per due
game before any LLM call), already cheap relative to a full ingest run.

**Alternatives considered**: A separate scheduled process — rejected, no capability gap it
would close that the shared-tick approach doesn't already cover, and it would duplicate the
existing due-run/poll machinery for no benefit.
