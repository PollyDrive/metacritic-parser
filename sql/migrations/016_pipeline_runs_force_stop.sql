-- Force-stop: an operator can cancel an in-flight pipeline run from
-- /monitoring. cancel_requested is a cooperative flag checked between items
-- (infrastructure/db/repositories.py's is_cancel_requested); 'cancelled' is a
-- terminal status distinct from 'failed' so the run history doesn't read as
-- an error the operator needs to investigate.
ALTER TABLE pipeline_runs ADD COLUMN IF NOT EXISTS cancel_requested BOOLEAN NOT NULL DEFAULT false;

ALTER TABLE pipeline_runs DROP CONSTRAINT IF EXISTS pipeline_runs_status_check;
ALTER TABLE pipeline_runs ADD CONSTRAINT pipeline_runs_status_check
    CHECK (status IN ('running', 'completed', 'failed', 'cancelled'));
