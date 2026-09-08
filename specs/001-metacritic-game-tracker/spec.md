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

### User Story 5 - Live Pipeline Monitoring & Manual Trigger (Priority: P5)

*(Optional scope — corresponds to "Дополнительная часть 2" in the source brief.)*

An operator watches the ingestion pipeline's status and processed-record counts update live, and can force an out-of-schedule run.

**Why this priority**: Operational visibility and control; explicitly marked as bonus/additional in the source brief.

**Independent Test**: Trigger the pipeline manually from the UI and observe status/progress counters update without a page reload.

**Acceptance Scenarios**:

1. **Given** the ingestion pipeline is running, **When** the operator opens the monitoring view, **Then** current worker status and processed-record counts update without a manual page refresh.
2. **Given** the operator wants an out-of-schedule run, **When** they press the manual-run control, **Then** a new ingestion run starts immediately and its progress is reflected in the monitoring view.

---

### Edge Cases

- What happens when Metacritic's page structure changes or blocks scraping mid-run?
- What happens when a game already in the catalog gains a platform release it didn't have before (re-crawled with a new platform entry)?
- What happens when a platform's Metascore or Userscore is marked "tbd" / not yet available?
- What happens when the same title appears once per platform on Metacritic — is that one catalog entry with multiple platform scores, or several entries? (Assumed: one entry, per FR-006/FR-007.)
- What happens when the YouTube video selected for a playthrough takeaway is later made private, deleted, or is region-locked at processing time?
- What happens when none of a game's scraped "Related Games" are (yet) present in the catalog — no similar games shown, no error.
- What happens when the "New Releases" and "See All / Newest" sources combined have fewer than 20 unprocessed games left for the day — the run processes however many remain rather than padding the count artificially.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST run an ingestion job automatically once per hour without manual intervention.
- **FR-002**: On the first ingestion run of each calendar day, System MUST source candidate games from Metacritic's "New Releases" section on the Games page.
- **FR-003**: On subsequent runs within the same calendar day, System MUST source candidate games from the "See All" browse listing sorted by newest, advancing to the next page of that listing on each run.
- **FR-004**: On each run, System MUST select at most 20 games that have not already been processed that calendar day.
- **FR-005**: System MUST reset its "already processed today" tracking at the start of each new calendar day and MUST resume sourcing from "New Releases" first. If "New Releases" yields fewer than 20 not-yet-processed games for the day, System MUST top up the remainder within the same run from the "See All / Newest" listing (starting at the correct page), so each run processes 20 games whenever the combined sources have that many left for the day.
- **FR-006**: For each selected game, System MUST capture: title, cover image, one or more platform entries (each with its own Metascore and Userscore), developer, description, a video link, and the list of games shown in that game's own "Related Games" section on Metacritic.
- **FR-007**: System MUST create a new catalog entry for a game not already in the database, and MUST update the existing entry if the game is already present.
- **FR-008**: System MUST generate a short summary of what critics like and dislike about the game, derived from critic reviews.
- **FR-009**: System MUST generate a short summary of what players like and dislike about the game, derived from user reviews, kept separate from the critic summary.
- **FR-010**: System MUST regenerate both review summaries whenever a game is re-processed on a later ingestion run.
- **FR-011**: The web interface MUST show a list of catalog games with brief info per game (at minimum: title, cover image, platform(s), score(s)).
- **FR-012**: The web interface MUST provide a per-game detail card showing every field captured under FR-006 plus both review summaries.
- **FR-013**: The web interface MUST let visitors filter the catalog list by platform.
- **FR-014**: The web interface MUST let visitors search the catalog by game title.
- **FR-015**: The web interface MUST let visitors sort the catalog list by rating.
- **FR-016**: For each game, System MUST determine its "similar games" by taking the "Related Games" list scraped per FR-006 and keeping only the entries that already exist as catalog games in this service's own database, then display that intersection on the game's detail card.
- **FR-017**: Clicking a similar game's name MUST open that game's own detail card.
- **FR-018** *(optional scope, User Story 4)*: For each game, System SHOULD locate its most popular YouTube playthrough video, transcribe its narration, produce a short takeaway, and attach that takeaway with a link to the source video.
- **FR-019** *(optional scope, User Story 5)*: The web interface SHOULD show real-time status of ingestion workers and the count of records processed during the current/most recent run.
- **FR-020** *(optional scope, User Story 5)*: The web interface SHOULD provide a control that lets an operator force an ingestion run to start immediately.
- **FR-021**: The core catalog (browse/search/filter/sort) MUST NOT require visitors to authenticate.
- **FR-022** *(optional scope, User Story 5)*: The monitoring view and the force-run control MUST be reachable only after the operator authenticates with a single, fixed username/password (no self-service registration or multi-user roles).

### Key Entities

- **Game**: Title, cover image, developer, description, video link, scraped "Related Games" list (raw, from Metacritic), first-seen date, last-updated timestamp; holds one or more Platform Scores, a critic review summary, a user review summary, and (optionally) a Playthrough Takeaway. "Similar games" shown in the UI are computed at read time (or cached) as the subset of the Related Games list that exists in this service's own database — not stored as a separate entity.
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

## Assumptions

- Calendar-day boundaries for the "process 20 new games per day" logic use the deployment's server local time/UTC; the brief does not specify a timezone.
- Metacritic's "New Releases", "See All" browse listing, and individual game pages remain scrapeable via standard HTTP requests (no official public API is assumed to exist for this data).
- The web interface serves a single tenant/operator; no multi-user account system is required for the core catalog experience (browse/search/filter/sort).
- User Stories 4 and 5 (playthrough takeaway, live monitoring + manual trigger) are optional/stretch scope layered on top of the mandatory core catalog (User Stories 1-3), consistent with the source brief labeling them "Дополнительная часть 1" and "Дополнительная часть 2".
- "Similar games" are computed from Metacritic's own "Related Games" list for that game, restricted to the subset already present in this service's own database — never fetched fresh from Metacritic at display time.
- The single operator login/password for the monitoring view (FR-022) is provisioned/configured out of band (e.g., environment variable or config file); self-service account creation is out of scope.
