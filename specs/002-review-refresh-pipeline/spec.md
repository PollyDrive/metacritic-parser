# Feature Specification: Review Refresh Pipeline

**Feature Branch**: `002-review-refresh-pipeline`

**Created**: 2026-09-09

**Status**: Draft

**Input**: User description: "раздели пайплан инжеста на 2, в первом забираем игры как по тз, во втором будем обновлять отзывы с агрессивно затухающей кривой обхода + триггером по дельте отзывов на кол-во отзывов. при первонаачальном инжесте надо сохранять сколько отзывов на игру уже есть в обеих категориях (миграцию добавь), во втором сначала скрапер (без LLM) обходит старые игры по кривой (если игре меньше недели – раз в 3 дня) и вызывает llm только если новых отзывов > чем имеющихся на дельту. потому что сначала все отзывы важны, потом уже они не особо повлияют"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Summaries Stay Representative as Reviews Accumulate (Priority: P1)

A visitor opens a game that was cataloged weeks ago. Since it was first summarized, the game has picked up substantially more critic and player reviews. The visitor sees a summary that reflects the fuller picture, not a snapshot frozen from the handful of reviews available on day one.

**Why this priority**: A summary that never updates becomes actively misleading as a game's review base grows — this is the core problem the feature exists to fix. Without it, every summary is permanently stuck at its first-day quality regardless of how much more evidence piles up later.

**Independent Test**: Seed a cataloged game with a recorded review count and an existing summary, simulate a later state where its actual review count has grown well past that recorded count, run a refresh pass, and confirm the summary and recorded count are both updated to reflect the new reviews.

**Acceptance Scenarios**:

1. **Given** a cataloged game whose critic review count has grown substantially since its summary was generated, **When** a refresh pass reaches that game, **Then** its critic summary is regenerated and its recorded critic review count is updated to the new total.
2. **Given** a cataloged game whose user review count has grown substantially while its critic review count has barely moved, **When** a refresh pass reaches that game, **Then** only the user summary is regenerated — the critic summary and its recorded count are left untouched.
3. **Given** a newly cataloged game with no prior summary, **When** the initial ingest pipeline processes it, **Then** the review counts observed at that first summarization are recorded per audience for later comparison.

---

### User Story 2 - Refresh Effort Concentrates Where It Still Matters (Priority: P2)

The operator does not want every cataloged game re-checked on the same fixed schedule forever, and does not want a summary regenerated (and its LLM cost spent) every time one or two new reviews trickle in. Recently released games — where review volume is still climbing fast and every summary update meaningfully changes what a visitor reads — get checked often. Older games, where a handful of new reviews barely shifts the overall picture, get checked rarely, and a small trickle of new reviews does not trigger a regeneration at all.

**Why this priority**: This is what makes User Story 1 affordable to run continuously instead of as a one-off. Without it, the refresh pipeline would either hammer Metacritic and the LLM budget checking everything constantly, or need to be run so conservatively that it stops delivering the freshness User Story 1 promises.

**Independent Test**: Seed games of varying ages and varying review-count growth since their last summary; run the refresh pass; confirm younger games are selected for a recheck more often than older ones over repeated passes, and confirm that games whose growth stays under the configured threshold are recheck-visited (counts refreshed) but never trigger a regeneration.

**Acceptance Scenarios**:

1. **Given** two cataloged games of different ages, **When** the refresh pipeline runs repeatedly over time, **Then** the game younger than one week is revisited roughly every 3 days while the older game is revisited on a wider interval.
2. **Given** a cataloged game whose review count has grown only slightly since its last summary, **When** a refresh pass reaches it, **Then** the system fetches the current counts but does not call the summarization service and does not change the existing summary.
3. **Given** a refresh pass is underway, **When** it checks a game's current review counts, **Then** it does so without invoking the summarization service — that service is only invoked afterward, and only for audiences that cleared the growth threshold.

---

### Edge Cases

- A game has zero recorded reviews for an audience at initial ingest (e.g., no user reviews yet), and later picks up its first few. Any non-zero count against a zero base counts as growth and is eligible to trigger a summary for that audience.
- A game's observed review count is *lower* than its last recorded count (e.g., Metacritic removed reviews as spam). This is not growth; the existing summary and recorded count are left as they are.
- A game reaches four weeks since being cataloged without its review growth ever having cleared the trigger threshold. It exits the refresh pass at that point and is not automatically revisited by this pipeline again, even if it later picks up a fresh wave of reviews (e.g., a remaster or anniversary re-release) — reactivating a game past this cutoff is out of scope for this feature.
- The number of games due for a recheck in a given pass exceeds what the pipeline can process before the next one starts. Games are prioritized by age (youngest-due first) so the fastest-moving, highest-value games are never starved by a backlog of older ones.
- A game is still missing its very first summary for an audience (the initial ingest's summarization call failed and the existing gap-filling process hasn't caught it yet). The refresh pipeline treats it as no prior recorded count — a non-zero observed count is growth and is eligible to trigger the first summary for that audience, rather than waiting indefinitely for the gap-filling process.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST record, separately for the critic audience and the user audience, the review count observed at the time each game's most recent summary for that audience was generated.
- **FR-002**: The initial ingest pipeline (new-game discovery and first-time cataloging) MUST populate these recorded counts at the same time it generates a game's first summaries, and MUST NOT depend on the refresh pipeline described below to do so.
- **FR-003**: System MUST run a review-refresh pass over already-cataloged games on a schedule that is independent of, and does not delay, the initial ingest pipeline's discovery of newly released games.
- **FR-004**: The refresh pass's revisit frequency for a given game MUST decay by the game's age since first being cataloged: games younger than one week are eligible for a recheck every 3 days; games between one and four weeks old are eligible for a recheck weekly; games four weeks or older are no longer included in refresh-pass rechecks at all.
- **FR-005**: A refresh-pass recheck MUST fetch each due game's current critic and user review counts without invoking the summarization service.
- **FR-006**: System MUST regenerate a game's summary for an audience only when the newly observed review count for that audience has grown past its recorded count by at least a configured amount (a significant-growth threshold), with any non-zero observed count against a zero recorded count always clearing the threshold. [Revised during implementation: the threshold is a flat review-count delta (`reviews.growth_threshold`, default 10), not a percentage of the recorded count. The observed/recorded counts it compares are also not summed across a game's platforms — reviews are split per platform on Metacritic, so each recheck picks whichever platform currently has the most reviews for that audience (`pick_best_platform`) and tracks growth against that one platform's total, which is more representative than an incomparable cross-platform sum (research.md §1, §4).]
- **FR-007**: When a recheck's growth does not clear the threshold for an audience, system MUST leave that audience's existing summary and recorded count unchanged, and MUST NOT invoke the summarization service for it.
- **FR-008**: When a summary is regenerated for an audience, system MUST update that audience's recorded review count to the newly observed count.
- **FR-009**: The critic and user audiences MUST be evaluated against the growth threshold, and regenerated, independently of each other for the same game.
- **FR-010**: The significant-growth threshold, the decay-curve intervals, and the age at which a game exits the refresh pass MUST all be adjustable without a code change.
- **FR-011**: A game whose observed review count for an audience is lower than its recorded count MUST NOT be treated as growth and MUST NOT trigger a regeneration.
- **FR-012**: System MUST prioritize younger due games over older due games when the number of games due for a recheck in a pass exceeds what the pass can process.

### Key Entities

- **Review Count Snapshot**: Per game, per audience (critic/user), the review count observed at the time that audience's summary was last generated — the baseline the refresh pass compares fresh counts against to decide whether growth clears the trigger threshold. Carried alongside the existing per-audience review summary.
- **Refresh Schedule State**: Per game, when it was first cataloged and when it was last rechecked by the refresh pass — drives which games are due and at what point on the decay curve they currently sit.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A game whose review counts have grown well past the significant-growth threshold since its last summary gets a refreshed summary within one full cycle of its age-appropriate revisit interval.
- **SC-002**: Games whose review counts grow only marginally between rechecks never have their summary regenerated purely by that marginal growth — regeneration volume tracks meaningful review growth, not recheck frequency.
- **SC-003**: A newly released game accumulating reviews quickly is revisited at least twice as often, during its first week, as a game in its second-to-fourth week.
- **SC-004**: The initial ingest pipeline's throughput and latency for discovering and cataloging new games are unaffected by how many already-cataloged games are due for a refresh recheck.

## Assumptions

- The refresh pipeline operates only on games that already have at least one prior recorded review count for an audience (i.e., that audience has already been summarized once, whether by the initial ingest pipeline or a prior refresh pass); a game still waiting on its very first summary for an audience is, per the Edge Cases above, treated as having a recorded count of zero for that audience, so it is picked up by the same growth check rather than requiring separate handling.
- "Games" in scope for the refresh pass are exactly the catalog's existing games — no new discovery or admission logic changes; the split is about when and how already-cataloged games get revisited, not about how new games are found.
- The refresh pass's age-based revisit interval is measured from when a game was first cataloged, not from when it was last released or updated on Metacritic.
- The decay curve is deliberately steep and finite: a game that hasn't cleared the growth threshold by four weeks after cataloging is assumed to have settled, and the refresh pass stops spending recheck capacity on it. A reasonable starting value for the significant-growth threshold (e.g., growth of roughly a quarter over the recorded count) will be chosen during planning and exposed as an adjustable setting per FR-010, consistent with this project's existing pattern of runtime-tunable operational parameters.
