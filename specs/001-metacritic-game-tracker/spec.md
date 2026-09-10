# Feature Specification: Metacritic Game Tracker

**Feature Branch**: `001-metacritic-game-tracker`

**Created**: 2026-09-08

**Status**: Draft

**Input**: User description: "Реализовать сервис, который 1 раз в час заходит на Metacritic в раздел Games берет новые 20 игр... [see docs/assignment.md for full brief]"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Browse Game Catalog (Priority: P1)

A visitor opens the service's web interface to see an up-to-date catalog of games pulled from Metacritic, and can open any game to see its full details in one place instead of visiting Metacritic directly.

**Why this priority**: This is the core value of the service — a browsable catalog built automatically from Metacritic data. Without it, nothing else in the spec has anything to display.

**Independent Test**: Seed the database with at least one processed game, load the catalog list, confirm brief info is shown, click into the game, confirm the full detail card renders every captured field.

**Acceptance Scenarios**:

1. **Given** games have been ingested into the system, **When** a visitor opens the catalog page, **Then** a list shows each game's title, cover image, and score(s) per platform.
2. **Given** a visitor is viewing the list, **When** they click a game, **Then** a card opens showing developer, description, video link, per-platform Metascore/Userscore, and both review summaries (critic and user).

---

### User Story 2 - Filter, Search, and Sort the Catalog (Priority: P2)

A visitor narrows down the growing catalog by platform, by title, or by rating to find what they're looking for.

**Why this priority**: The catalog accumulates 20 games per hour; without narrowing tools it quickly becomes unusable.

**Independent Test**: Load multiple games spanning different platforms and ratings, apply each control independently, verify results match.

**Acceptance Scenarios**:

1. **Given** the catalog has games on multiple platforms, **When** a visitor selects a platform filter, **Then** only games available on that platform are shown.
2. **Given** the catalog has many games, **When** a visitor types a game title (or part of one) into search, **Then** matching games are shown.
3. **Given** the catalog has games with different ratings, **When** a visitor sorts by rating, **Then** games are ordered by rating.

---

### User Story 3 - Discover Similar Games (Priority: P3)

While viewing a game's card, a visitor sees other games in the catalog that are similar, and can jump straight to any of them.

**Why this priority**: Turns a flat list into a browsable, connected catalog and is called out in the brief as a distinct piece of value beyond raw scraped data.

**Independent Test**: Seed two or more games that qualify as similar, open one's card, confirm the others appear in a "similar games" section, click through to confirm navigation.

**Acceptance Scenarios**:

1. **Given** at least one other catalog game qualifies as similar, **When** a visitor opens a game's card, **Then** a "similar games" section lists them.
2. **Given** the similar games section is shown, **When** a visitor clicks a similar game's name, **Then** that game's own card opens.

---

### User Story 4 - Playthrough-Based Takeaway (Priority: P4)

*(Optional scope — corresponds to "Дополнительная часть 1" in the source brief.)*

A visitor reads a short takeaway distilled from the most popular YouTube playthrough of a game, alongside a link to the source video.

**Why this priority**: Adds narrative, player-voice context beyond numeric scores; explicitly marked as bonus/additional in the source brief, so it should not block the core catalog.

**Independent Test**: For a game with a known public playthrough video, run the enrichment step and confirm a takeaway plus video link is attached.

**Acceptance Scenarios**:

1. **Given** a game has at least one public YouTube playthrough video, **When** the enrichment step runs for that game, **Then** the most-viewed playthrough is identified, its narration is transcribed, and a short takeaway is attached along with a link to the source video.
2. **Given** a game has no findable playthrough, **When** enrichment runs, **Then** the game is left without a takeaway and no error is surfaced to catalog visitors.

---

### User Story 5 - Operator Console: Monitoring, Manual Trigger & Live Settings (Priority: P5)

*(Monitoring and manual trigger correspond to "Дополнительная часть 2" in the source brief; live settings are an added operator requirement.)*

An operator watches the ingestion pipeline's status and processed-record counts update live, can force an out-of-schedule run, and can retune how ingestion behaves — cadence, active hours, batch size, request delay, review sample sizes, enrichment budget — without a redeploy.

**Why this priority**: Operational visibility and control. The settings half matters because these are precisely the values whose correct setting is discovered by watching the pipeline run; if changing them requires a redeploy, they never get changed.

**Independent Test**: Trigger the pipeline manually from the UI and observe status/progress counters update without a page reload; change a setting and confirm the next run uses the new value.

**Acceptance Scenarios**:

1. **Given** the ingestion pipeline is running, **When** the operator opens the monitoring view, **Then** current worker status and processed-record counts update without a manual page refresh.
2. **Given** the operator wants an out-of-schedule run, **When** they press the manual-run control, **Then** a new ingestion run starts immediately and its progress is reflected in the monitoring view.
3. **Given** the operator changes a setting (e.g. games per run, or active hours), **When** they save it, **Then** the change is persisted and the next ingestion run uses the new value with no restart.
4. **Given** the operator enters a value outside the permitted range (e.g. a request delay of 0), **When** they try to save, **Then** the change is rejected with an explanation and the previous value stays in effect.
5. **Given** an unauthenticated visitor, **When** they request the settings page, **Then** access is refused.

---

### Edge Cases

- What happens when Metacritic's page structure changes or blocks scraping mid-run? (A block/challenge response must be recorded as a distinct failure — never counted as "this listing had no games".)
- What happens when a game is scraped and saved but its review summarization fails partway (e.g. LLM timeout)? Per FR-023 the game must not be treated as finished; the missing summary is completed on a later run.
- What happens when a game already in the catalog gains a platform release it didn't have before (re-crawled with a new platform entry)?
- What happens when a platform's Metascore or Userscore is marked "tbd" / not yet available?
- What happens when the same title appears once per platform on Metacritic — is that one catalog entry with multiple platform scores, or several entries? (Assumed: one entry, per FR-006/FR-007.)
- What happens when the YouTube video selected for a playthrough takeaway is later made private, deleted, or is region-locked at processing time?
- What happens when no other catalog game shares a genre with this one (yet) — no similar games shown, no error.
- What happens when the "New Releases" and "See All / Newest" sources combined have fewer than 20 unprocessed games left for the day — the run processes however many remain rather than padding the count artificially.
- What happens when a run's "New Releases" listing has zero games not already in the catalog — System falls back to the "See All / Newest" listing for that run instead (FR-003).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST run an ingestion job automatically on a recurring schedule (default: once per hour) without manual intervention, and MUST skip scheduled runs outside the configured active-hours window. Cadence and active hours are operator-adjustable per FR-025.
- **FR-002**: On every ingestion run, System MUST source candidate games from Metacritic's "New Releases" section on the Games page (`/game/`) first. [Revised 2026-09-10: previously "New Releases" was only checked on the day's first run — see FR-005.]
- **FR-003**: When "New Releases" yields zero games not already in the catalog, System MUST fall back that run to the "See All" browse listing sorted by newest (`/browse/game/all/all/all-time/new/`), at a forward-only pagination cursor that advances one page each time the fallback is actually used. A run whose "New Releases" pass finds at least one not-yet-known game does not touch "See All" at all that run, and its cursor is unaffected. [Revised 2026-09-10: previously "See All" advanced on every run after the day's first, with "New Releases" checked only once daily — see FR-005.]
- **FR-004**: On each run, System MUST select at most 20 games that have not already been processed that calendar day.
- **FR-005**: System MUST reset its per-day processed-count tracking at the start of each new calendar day. [Revised 2026-09-10: "New Releases" is no longer a once-per-calendar-day pass — every run tries it first and falls back to "See All" only when "New Releases" has no not-yet-known games that run (FR-002/FR-003). This makes drift correction inherent (a game published mid-day is caught by the very next run's "New Releases" check), so the previous design's always-on "See All" page-1 recheck is gone — it existed only to compensate for "New Releases" being checked once per day. Prior text, superseded: "System MUST reset its 'already processed today' tracking at the start of each new calendar day and MUST resume sourcing from 'New Releases' first. If 'New Releases' yields fewer than 20 not-yet-processed games for the day, System MUST top up the remainder within the same run from the 'See All / Newest' listing... on every run *after* the day's first, System ALSO always rechecks 'See All / Newest' page 1 as a second, fixed top-up source..." (domain/rules.py's `advance_state`, research.md §12).]
- **FR-006**: For each selected game, System MUST capture: title, cover image, one or more platform entries (each with its own Metascore and Userscore), developer, description, a video link, and its genre tag(s) as listed on Metacritic. [Corrected during implementation: the game detail page's own data does not include a "Related Games" list — that section on the live site is populated by a separate genre-filtered query against an undocumented internal endpoint, not by data attached to the game itself. Genre tags are present on the game's own page and are what similar-games (FR-016) is actually computed from.]
- **FR-007**: System MUST create a new catalog entry for a game not already in the database, and MUST update the existing entry if the game is already present.
- **FR-008**: System MUST generate a short summary of what critics like and dislike about the game, derived from a representative sample of critic reviews — not only the few excerpts featured on the game's main page.
- **FR-009**: System MUST generate a short summary of what players like and dislike about the game, derived from a representative sample of user reviews, kept separate from the critic summary.
- **FR-010**: System MUST regenerate a review summary when none exists yet for a game (including after a prior generation attempt failed), via the same backfill mechanism as FR-023. Per the Decayed TTL rules, System MUST ALSO regenerate a summary if the game's `next_refresh_at` is due.
- **FR-023**: System MUST detect catalog games that are missing any enrichment output (critic summary, user summary, or — in optional scope — playthrough takeaway) and complete them on a later run, without waiting for the game to reappear in a Metacritic source listing. Repeated failures for the same game MUST back off and eventually stop being retried, and MUST be recorded with a reason rather than silently dropped.
- **FR-024**: Enrichment steps MUST run only on games admitted as new by deduplication, missing that output, or due for a review refresh based on Decayed TTL. A game whose reviews are fresh according to the TTL rules MUST NOT trigger repeat enrichment work.
- **FR-025**: Operational settings MUST be adjustable at runtime without a redeploy or restart, and MUST take effect from the next ingestion run. At minimum: whether scheduled ingestion is enabled, how often it runs, the active hours window and its timezone, how many games are taken per run, the delay between outbound requests, how many reviews are sampled per audience, whether playthrough enrichment is enabled and its daily search budget, and the retry ceiling/backoff for failed enrichment.
- **FR-026**: The settings interface MUST be reachable only by an authenticated operator (same credentials as FR-022), MUST validate every value against a permitted range on the server before saving, and MUST NOT expose or accept secrets (API keys, database credentials). Each change MUST record who made it and when.
- **FR-027**: Before any scraped data is written to the catalog, System MUST validate it against a declared set of data-quality rules covering (a) whether the source still matches its expected structure and (b) whether each individual record has its required fields present and its values in range. Every failure MUST be recorded with the specific rule that failed and enough of the input to re-judge it — never discarded silently.
- **FR-028**: A record missing a field that is required but recoverable (description, developer, cover image) MUST still enter the catalog and MUST be queued for re-extraction, rather than being discarded. A record that cannot be identified or displayed at all (no stable id, no title, no platform) MUST NOT enter the catalog.
- **FR-029**: When the source no longer matches its expected structure, or when the share of records failing validation in one run exceeds a configured limit, System MUST abort that run without writing partial results and without advancing its position in the source listing, so that no games are skipped as a side effect of the failure.
- **FR-030**: A source-structure validation failure (FR-029) MUST be logged at a critical severity with enough detail to diagnose it, and an email alert MUST be sent via the Resend API. This project has no dashboard; the application log and email alerts are the mechanism.
- **FR-011**: The web interface MUST show a list of catalog games with brief info per game (at minimum: title, cover image, platform(s), score(s)).
- **FR-012**: The web interface MUST provide a per-game detail card showing every field captured under FR-006 plus both review summaries.
- **FR-013**: The web interface MUST let visitors filter the catalog list by platform.
- **FR-014**: The web interface MUST let visitors search the catalog by game title.
- **FR-015**: The web interface MUST let visitors sort the catalog list by rating.
- **FR-016**: For each game, System MUST determine its "similar games" as other catalog games sharing at least one genre tag (captured per FR-006), ordered by Metascore, and display them on the game's detail card.
- **FR-017**: Clicking a similar game's name MUST open that game's own detail card.
- **FR-018** *(optional scope, User Story 4)*: For each game, System SHOULD locate its most popular YouTube playthrough video, transcribe its narration, produce a short takeaway, and attach that takeaway with a link to the source video. Playthrough discovery MUST operate within a bounded daily search budget; when the budget is exhausted, remaining games stay unenriched and are picked up on a later day (no error surfaced to catalog visitors).
- **FR-019** *(optional scope, User Story 5)*: The web interface SHOULD show real-time status of ingestion workers and the count of records processed during the current/most recent run.
- **FR-020** *(optional scope, User Story 5)*: The web interface SHOULD provide a control that lets an operator force an ingestion run to start immediately.
- **FR-021**: The core catalog (browse/search/filter/sort) MUST NOT require visitors to authenticate.
- **FR-022** *(optional scope, User Story 5)*: The monitoring view and the force-run control MUST be reachable only after the operator authenticates with a single, fixed username/password (no self-service registration or multi-user roles).

### Key Entities

- **Game**: Title, cover image, developer, description, video link, genre tag(s), first-seen date, last-updated timestamp; holds one or more Platform Scores, a critic review summary, a user review summary, and (optionally) a Playthrough Takeaway. "Similar games" shown in the UI are computed at read time as other catalog games sharing a genre tag — not stored as a separate entity.
- **Platform Score**: Platform name (e.g., PS5, Switch 2), Metascore, Userscore; belongs to one Game.
- **Playthrough Takeaway** *(optional scope)*: Source video URL, the takeaway text derived from its transcript; belongs to one Game.
- **Ingestion Run** *(optional scope for monitoring)*: Start time, source used (New Releases, or See All page N), games processed count, status.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A visitor can locate a specific known game by title in under 10 seconds using search.
- **SC-002**: A new Metacritic release appears in the catalog within 1 hour of appearing on the source site.
- **SC-003**: Every catalog entry displays a Metascore and/or Userscore for each platform Metacritic lists for that game, whenever Metacritic itself provides that score.
- **SC-004**: A game's card surfaces at least one similar game whenever another qualifying game exists in the catalog.
- **SC-005** *(optional scope)*: An operator can tell whether the ingestion pipeline is idle, running, or failed within 5 seconds of opening the monitoring view.
- **SC-006** *(business outcome; baseline = visiting Metacritic manually)*: A visitor can decide whether a game is worth their time — per-platform scores, what critics and players liked and disliked, and what else they might play — without leaving the catalog. Volume processed is explicitly NOT a measure of this.
- **SC-007** *(judgement quality)*: On a human-rated sample of games, at least 80% of generated review summaries make claims that are actually supported by the reviews they were derived from. Re-rated whenever the summarization prompt or model changes.

## Assumptions

- Calendar-day boundaries for the "process 20 new games per day" logic use the deployment's server local time/UTC; the brief does not specify a timezone.
- Metacritic's "New Releases", "See All" browse listing, per-game pages, and per-game `/critic-reviews` + `/user-reviews` pages remain reachable via HTTP requests from a browser-like client (no official public API is assumed to exist for this data).
- Playthrough enrichment (optional scope) is rate-bound by the YouTube Data API's free daily quota, so coverage accrues over days rather than matching the ingestion rate one-for-one; partial coverage is an expected steady state, not a defect.
- The web interface serves a single tenant/operator; no multi-user account system is required for the core catalog experience (browse/search/filter/sort).
- User Stories 4 and 5 (playthrough takeaway, live monitoring + manual trigger) are optional/stretch scope layered on top of the mandatory core catalog (User Stories 1-3), consistent with the source brief labeling them "Дополнительная часть 1" and "Дополнительная часть 2".
- "Similar games" are computed from genre overlap against this service's own catalog — never fetched fresh from Metacritic at display time. (Revised during implementation: Metacritic's own game-detail data has no "Related Games" list to intersect against; the live site's "Related Games" section is generated by a genre-filtered query against an undocumented endpoint, not scraped data — see FR-006.)
- The single operator login/password for the monitoring view (FR-022) is provisioned/configured out of band (e.g., environment variable or config file); self-service account creation is out of scope.
