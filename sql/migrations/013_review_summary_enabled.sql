-- FR-001/FR-003: independent master switch for review-summary generation,
-- same shape as the existing enrichment.playthrough_enabled row.
INSERT INTO runtime_config (key, value, value_type, min_value, max_value, description) VALUES
    ('enrichment.review_summary_enabled', 'true', 'bool', NULL, NULL,
     'Master switch for review-summary generation (critic/user) — both the inline call during '
     'ingest and the scheduled review-refresh pass. Off also stops the userscore refresh that '
     'piggybacks on the same source-site check.')
ON CONFLICT (key) DO NOTHING;
