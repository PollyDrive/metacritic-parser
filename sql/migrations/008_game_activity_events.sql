CREATE TABLE game_activity_events (
    id SERIAL PRIMARY KEY,
    game_id INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    run_id INTEGER REFERENCES pipeline_runs(id) ON DELETE SET NULL,
    event_type TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    details JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX idx_game_activity_events_game_id ON game_activity_events(game_id);
CREATE INDEX idx_game_activity_events_run_id ON game_activity_events(run_id);
CREATE INDEX idx_game_activity_events_created_at ON game_activity_events(created_at);

ALTER TABLE review_summaries ADD COLUMN parsed_reviews_count INTEGER NOT NULL DEFAULT 0;
