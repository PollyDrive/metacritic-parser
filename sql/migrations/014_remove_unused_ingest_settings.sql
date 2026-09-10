-- Removed: no active-hours concept (ingest runs whenever due, per the brief),
-- cadence fixed at once per hour (not operator-tunable), and the day-boundary
-- timezone was never actually retuned in practice — hardcoded to UTC in code
-- instead (application/ingest.py, infrastructure/scheduler/tick.py).
DELETE FROM runtime_config WHERE key IN (
    'ingest.active_hours_start',
    'ingest.active_hours_end',
    'ingest.runs_per_hour',
    'ingest.timezone'
);
