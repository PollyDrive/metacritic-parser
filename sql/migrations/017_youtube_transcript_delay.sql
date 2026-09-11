-- Politeness delay before every YouTube transcript fetch attempt (not just
-- retries) — a residential IP hit the same RequestBlocked/IpBlocked error
-- as the VPS, which points at request-burst rate limiting rather than pure
-- datacenter-IP reputation. Mirrors scraper.request_delay_seconds.
INSERT INTO runtime_config (key, value, value_type, min_value, max_value, description)
VALUES (
    'enrichment.youtube_transcript_delay_seconds',
    '2',
    'float',
    0,
    30,
    'Politeness delay before each YouTube transcript fetch attempt (per ranked candidate, per game)'
)
ON CONFLICT (key) DO NOTHING;
