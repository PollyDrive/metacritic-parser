-- FR-002/003 revised: New Releases is now tried on every ingestion run (not
-- just the day's first), falling back to See All only when New Releases has
-- zero not-yet-known games that run. The once-per-day flag no longer means
-- anything.
ALTER TABLE ingest_state DROP COLUMN IF EXISTS day_new_releases_done;
