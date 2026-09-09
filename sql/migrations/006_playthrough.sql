-- US4 (optional scope): playthrough takeaway + persisted YouTube quota spend.
CREATE TABLE IF NOT EXISTS playthrough_takeaways (
    id                              SERIAL PRIMARY KEY,
    game_id                         INTEGER NOT NULL UNIQUE REFERENCES games(id) ON DELETE CASCADE,
    video_url                       TEXT NOT NULL,
    video_view_count_at_selection   BIGINT,
    takeaway_text                   TEXT NOT NULL,
    generated_at                    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    llm_call_id                     INTEGER REFERENCES llm_calls(id) ON DELETE SET NULL
);

-- Persisted rather than counted in memory: a worker restart must not silently
-- reset the day's spend and blow the YouTube Data API daily quota (research.md §6).
CREATE TABLE IF NOT EXISTS youtube_quota_usage (
    usage_date    DATE PRIMARY KEY,
    search_calls  INTEGER NOT NULL DEFAULT 0,
    units_spent   INTEGER NOT NULL DEFAULT 0
);
