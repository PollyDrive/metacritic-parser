-- The review-count delta shown in monitoring is derived from
-- game_activity_events (the most recent matching event per game/audience),
-- not a stored counter — this column was never read after 008 wired that up.
ALTER TABLE review_summaries DROP COLUMN parsed_reviews_count;
