-- Singleton pagination cursor + daily progress (research.md §12). Without this,
-- a restart silently resumes pagination from page 1 forever.
CREATE TABLE IF NOT EXISTS ingest_state (
    id                     SMALLINT PRIMARY KEY CHECK (id = 1),
    current_day            DATE        NOT NULL,
    day_processed_count    INTEGER     NOT NULL DEFAULT 0,
    day_new_releases_done  BOOLEAN     NOT NULL DEFAULT false,
    see_all_next_page      INTEGER     NOT NULL DEFAULT 1,
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
-- UTC, not CURRENT_DATE (server session timezone) — must agree with the
-- application's day_key(now, ingest.timezone), or day-rollover logic disagrees
-- with itself the moment server-local and UTC dates diverge (caught by a test
-- that only failed when the machine running it wasn't on UTC).
INSERT INTO ingest_state (id, current_day, day_processed_count, day_new_releases_done, see_all_next_page)
VALUES (1, (NOW() AT TIME ZONE 'UTC')::date, 0, false, 1)
ON CONFLICT (id) DO NOTHING;

-- Retry/backoff bookkeeping for the backfill derived work queue (FR-023, research.md §7).
CREATE TABLE IF NOT EXISTS enrichment_attempts (
    id              SERIAL PRIMARY KEY,
    game_id         INTEGER     NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    step            TEXT        NOT NULL CHECK (step IN ('critic_summary','user_summary','playthrough')),
    attempts        INTEGER     NOT NULL DEFAULT 1,
    state           TEXT        NOT NULL DEFAULT 'retrying' CHECK (state IN ('retrying','abandoned')),
    last_error      TEXT,
    last_attempt_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    next_retry_at   TIMESTAMPTZ NOT NULL,
    UNIQUE (game_id, step)
);

-- Manual out-of-schedule trigger (FR-020, research.md §3) — enqueued by the web
-- tier, consumed by the worker; the web tier never runs ingestion in-process.
CREATE TABLE IF NOT EXISTS run_requests (
    id            SERIAL PRIMARY KEY,
    requested_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    picked_up_at  TIMESTAMPTZ,
    run_id        INTEGER REFERENCES pipeline_runs(id) ON DELETE SET NULL
);
