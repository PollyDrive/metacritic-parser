-- Operator-tunable settings (FR-025/026, research.md §11). Operational values
-- only — never secrets. Bounds enforced server-side, not just in the browser.
CREATE TABLE IF NOT EXISTS runtime_config (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    value_type  TEXT NOT NULL CHECK (value_type IN ('int','float','bool','string','time')),
    min_value   NUMERIC,
    max_value   NUMERIC,
    description TEXT,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_by  TEXT
);

INSERT INTO runtime_config (key, value, value_type, min_value, max_value, description) VALUES
    ('ingest.enabled',                       'true',  'bool',   NULL,  NULL,     'Master switch for scheduled ingestion'),
    ('ingest.runs_per_hour',                 '1',     'int',    1,     12,       'Cadence (FR-001)'),
    ('ingest.games_per_run',                 '20',    'int',    1,     100,      'Batch size (FR-004)'),
    ('ingest.active_hours_start',            '00:00', 'time',   NULL,  NULL,     'Start of the active window'),
    ('ingest.active_hours_end',              '24:00', 'time',   NULL,  NULL,     'End of the active window'),
    ('ingest.timezone',                      'UTC',   'string', NULL,  NULL,     'Calendar-day boundary timezone (FR-005)'),
    ('scraper.request_delay_seconds',        '1.5',   'float',  0.5,   30,       'Politeness delay (research.md §5)'),
    ('scraper.max_retries',                  '3',     'int',    0,     10,       'Retry attempts on transient failure'),
    ('scraper.timeout_seconds',              '30',    'int',    5,     120,      'Per-request timeout'),
    ('reviews.critic_sample_size',           '20',    'int',    1,     100,      'Reviews fed to critic summarization (research.md §8)'),
    ('reviews.user_sample_size',             '20',    'int',    1,     100,      'Reviews fed to user summarization'),
    ('enrichment.playthrough_enabled',       'false', 'bool',   NULL,  NULL,     'US4 master switch (optional scope)'),
    ('enrichment.youtube_daily_search_budget','1000', 'int',    0,     100000,   'Quota rail (research.md §6) — one search costs 100 units (SEARCH_COST_UNITS), so this must stay >= 100 or playthrough search never runs'),
    ('backfill.max_attempts',                '5',     'int',    1,     20,       'Attempt ceiling before abandoning (FR-023)'),
    ('backfill.backoff_base_minutes',        '30',    'int',    1,     1440,     'Exponential backoff base'),
    ('dq.max_reject_ratio',                  '0.25',  'float',  0.01,  1.0,      'Run-abort threshold on Gate B rejects (research.md §14.2)')
ON CONFLICT (key) DO NOTHING;
