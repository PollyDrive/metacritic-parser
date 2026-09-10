# Feature Specification: Independent Pipeline Enable Switches

**Feature Branch**: `003-pipeline-toggles`

**Created**: 2026-09-10

**Status**: Draft

**Input**: User description: "сделай свитчер, который управляет загрузкой каждого пайплайна. Если выкл, мы не парсим/не генерируем саммари/не ищем летсплеи. Все работают отдельно: если включен только саммари, то будет только апдейт старых игр., same for playthrough"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Turn Off Review-Summary Generation Only (Priority: P1)

An operator wants to stop spending LLM budget on critic/user review summaries — for a
newly-discovered game or an existing one whose reviews have grown — without touching game
discovery or playthrough search.

**Why this priority**: Today there is no way to fully stop summary generation. A brand-new
game with no prior summary is always summarized on its very first pass, regardless of any
other setting — the only existing lever (the growth-threshold) has no effect on that case. This
is the one pipeline an operator currently cannot turn off at all, making it the most valuable
and most broken gap this feature closes.

**Independent Test**: With this switch off, run both a normal ingestion pass (bringing in new
games) and a review-refresh pass (revisiting existing games); confirm neither produces a new or
updated summary for any game, while both the catalog and any playthrough takeaways continue to
update normally.

**Acceptance Scenarios**:

1. **Given** review-summary generation is turned off, **When** a brand-new game is discovered,
   **Then** it is added to the catalog with no critic or user summary, and none is generated for
   it later while the switch stays off.
2. **Given** review-summary generation is turned off, **When** an already-cataloged game's
   review count grows well past what its existing summary reflects, **Then** that summary is
   left exactly as it was — not regenerated, not removed.
3. **Given** review-summary generation is turned back on, **When** the next relevant pass runs,
   **Then** games that would have been summarized while it was off are picked up normally, with
   no need for a restart.

---

### User Story 2 - Turn Off New-Game Discovery Only (Priority: P2)

An operator wants to pause bringing new games into the catalog — e.g., because the source site
is misbehaving, or the catalog has reached a size they're happy with — while summaries keep
getting refreshed and playthroughs keep getting found for the games already in the catalog.

**Why this priority**: Slightly lower priority than User Story 1 because a version of this
switch already exists; this story's job is to guarantee — and make testable — that it never
affects the other two pipelines, which today is true by construction but has never been an
explicit, verified contract.

**Independent Test**: With this switch off, confirm no new game appears in the catalog over
several pipeline cycles, while a game already in the catalog still gets a fresh summary once its
reviews grow enough, and still gets a playthrough takeaway found for it if it lacks one.

**Acceptance Scenarios**:

1. **Given** new-game discovery is turned off, **When** the pipeline would otherwise have found
   new releases, **Then** the catalog's game count does not increase.
2. **Given** new-game discovery is turned off and review-summary generation is on, **When** a
   review-refresh pass runs, **Then** it still updates summaries for games already in the
   catalog — discovery being off does not pause it.
3. **Given** new-game discovery is turned off and playthrough search is on, **When** a
   playthrough pass runs, **Then** it still searches for takeaways for games already in the
   catalog.

---

### User Story 3 - Turn Off Playthrough Search Only (Priority: P2)

An operator wants to stop spending the daily video-search budget and LLM cost on playthrough
takeaways, without affecting new-game discovery or review summaries.

**Why this priority**: Same rationale as User Story 2 — a version of this switch already
exists; this story makes its independence from the other two pipelines an explicit, tested
guarantee rather than an incidental fact.

**Independent Test**: With this switch off, run discovery and review-refresh passes over
several cycles; confirm no playthrough takeaway is added for any game, new or existing, while
the catalog and its summaries continue to update normally.

**Acceptance Scenarios**:

1. **Given** playthrough search is turned off, **When** a new game with a well-known public
   playthrough is discovered, **Then** no takeaway is looked up or attached for it.
2. **Given** playthrough search is turned off, **When** an existing game still lacking a
   takeaway would otherwise be picked up, **Then** it is left without one and is not counted as
   a failure.
3. **Given** playthrough search is turned back on, **When** the next relevant pass runs,
   **Then** games missed while it was off become eligible again, with no need for a restart.

---

### Edge Cases

- All three switches off: the pipelines do nothing — no outbound requests to the source site,
  video platform, or LLM provider — while the catalog already built stays fully browsable.
- All three switches on: behavior matches today's default, unchanged.
- A switch is flipped off while games are already queued for that pipeline's next pass: those
  games are neither processed nor counted as failed — they simply wait, untouched, for the
  switch to be turned back on.
- An operator forces an immediate, out-of-schedule run of a specific pipeline while that
  pipeline's own switch is off: the explicit manual instruction proceeds anyway — a switch
  governs the automatic schedule, not a deliberate operator override (consistent with how a
  manual ingestion run already bypasses the discovery switch and active-hours window today).
- Turning a switch off never deletes or hides data already produced — an existing summary or
  playthrough takeaway stays visible to catalog visitors regardless of the switch's current
  state.
- Review-summary generation is off for an extended period: a game's displayed user rating can go
  stale (not just its summary), since the rating refresh piggybacks on the same source-site
  check the summary decision is based on — this is the accepted trade-off for making "off" mean
  zero source-site requests from this pipeline.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST provide three independent enable settings — one for new-game
  discovery, one for review-summary generation, one for playthrough search — each of which can
  be turned on or off without affecting the other two.
- **FR-002**: When new-game discovery is off, System MUST NOT add any new game to the catalog,
  and MUST leave already-cataloged games and their enrichment untouched by this setting.
- **FR-003**: When review-summary generation is off, System MUST NOT generate or regenerate a
  critic or user review summary for any game — whether newly discovered or already
  cataloged — regardless of how much its review count has grown or whether it has never been
  summarized before.
- **FR-004**: When review-summary generation is off, an existing summary already stored for a
  game MUST remain exactly as it was and MUST continue to be shown to catalog visitors.
- **FR-005**: When playthrough search is off, System MUST NOT look up or generate a playthrough
  takeaway for any game — whether newly discovered or already cataloged.
- **FR-006**: When review-summary generation is on but new-game discovery is off, only games
  already in the catalog are eligible to have a summary generated or refreshed — no newly
  discovered game contributes to this while discovery is off, because none arrive.
- **FR-007**: When playthrough search is on but new-game discovery is off, only games already in
  the catalog are eligible to have a playthrough takeaway searched for.
- **FR-008**: Each of the three settings from FR-001 MUST take effect on the next relevant
  pipeline run without requiring a restart, matching the operator-adjustable settings pattern
  already established for this system.
- **FR-009**: An operator-initiated, out-of-schedule run of a specific pipeline (as opposed to
  its normal automatic schedule) MUST proceed regardless of that pipeline's own enable setting —
  consistent with how an existing manual trigger already overrides the discovery schedule.
- **FR-010**: When review-summary generation is off, System MUST NOT refresh a game's
  publicly-displayed user rating from the source site either, since today that refresh is a side
  effect of the same review-growth check a summary regeneration decision is based on — turning
  the pipeline off means zero source-site requests on its behalf, and the rating may go stale
  until the pipeline is turned back on. (Resolved with the operator: this trade-off — no
  requests at all while off, over always-fresh ratings — is the intended behavior.)

### Key Entities

- **Pipeline Enable Setting**: One boolean per pipeline (discovery, review-summary generation,
  playthrough search), independently adjustable by an operator, read fresh by each pipeline run,
  requiring no restart to take effect. Extends this system's existing operator-tunable settings
  (spec 001's own operational-settings entity) rather than introducing a new mechanism.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An operator can turn off review-summary generation and, within one pipeline cycle,
  confirm zero new or updated summaries were produced and zero LLM cost was incurred, while the
  catalog's game count and playthrough coverage continue to grow normally.
- **SC-002**: An operator can turn off new-game discovery and confirm the catalog's game count
  stops growing while existing games' summaries and playthrough coverage continue to update.
- **SC-003**: An operator can turn off playthrough search and confirm no playthrough takeaway
  appears for any game, new or old, while discovery and summaries continue unaffected.
- **SC-004**: Flipping any one of the three settings takes effect within one pipeline cycle,
  with no service restart.
- **SC-005**: With all three settings off, the system makes zero outbound requests to the source
  site, the video platform, or the LLM provider from its background pipelines, while continuing
  to serve the existing catalog to visitors without interruption.

## Assumptions

- Recovering a game's missing recoverable fields (description, developer, cover image) is repair
  work on games already in the catalog, not discovery of new ones — per FR-002, it is unaffected
  by the discovery switch and keeps running on its own existing schedule regardless of that
  setting. [Corrected during planning: an earlier draft of this assumption said the opposite,
  which directly contradicted FR-002's own text once compared side by side — research.md §4.] It
  remains outside this feature's three switches; it is not a fourth, separately switchable
  pipeline.
- The review-summary setting fully supersedes today's only indirect lever (a very high
  growth-threshold value): with the setting off, no summary is generated under any
  circumstance, including a game's very first, always-eligible summary.
- Playthrough search's enable setting already exists in the system as a master on/off flag; this
  feature's scope for it is to make its independence from the other two pipelines an explicit,
  tested guarantee, not to introduce new mechanics.
- New-game discovery's own on/off behavior already exists in the system; this feature's scope
  for it is likewise to confirm and guarantee independence, not to introduce new mechanics.
- A manual, operator-triggered run of a specific pipeline overrides that pipeline's own enable
  setting, consistent with existing precedent for discovery's manual trigger.
