-- Lets an operator trigger one of the three pipelines independently
-- (ingest / review_refresh / playthrough) instead of one shared "Run now".
-- NULL on pre-existing rows means "ingest" (the only kind that existed before).
ALTER TABLE run_requests
ADD COLUMN kind TEXT NULL;
