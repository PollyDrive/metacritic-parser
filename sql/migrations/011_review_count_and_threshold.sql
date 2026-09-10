-- Metacritic's own review-listing JSON API (backend.metacritic.com) gives a
-- real per-platform review count and paginates past the SSR page's fixed
-- 10-review cap. Reviews are split per platform on Metacritic — this is
-- what actually lets review_summaries track what a summary reflects: the
-- true total on the platform it was sampled from, how many of those were
-- fed to the LLM, which platform that was, and a link back to the source.
ALTER TABLE review_summaries
    ADD COLUMN IF NOT EXISTS total_reviews_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS sampled_reviews_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS source_url TEXT,
    ADD COLUMN IF NOT EXISTS source_platform TEXT;

-- The 10-review SSR cap from migration 010 is superseded: the JSON API's real
-- per-request cap is also 10, but it paginates, so up to 20 reviews can be
-- pulled from the winning platform per regeneration (2 requests). SSR
-- parsing stays as the fallback when the JSON API's shape breaks — its own
-- 10-review ceiling, and lack of platform scoping, are unrelated to this
-- config value now.
UPDATE runtime_config SET
    value = '20',
    max_value = 20,
    description = 'Reviews fed to critic summarization, sampled from whichever platform has the most critic reviews for this game — Metacritic''s JSON review API paginates past its own 10-per-request cap, so up to 20 is reachable (2 requests); the SSR-page fallback used when that API''s shape breaks is still capped at 10 regardless of this value'
WHERE key = 'reviews.critic_sample_size';

UPDATE runtime_config SET
    value = '20',
    max_value = 20,
    description = 'Reviews fed to user summarization, sampled from whichever platform has the most user reviews for this game — see ''Critic reviews for summary'''
WHERE key = 'reviews.user_sample_size';

INSERT INTO runtime_config (key, value, value_type, min_value, max_value, description) VALUES
    ('reviews.growth_threshold', '10', 'int', 1, 1000,
     'A review-refresh recheck regenerates a summary only once the winning platform''s review count has grown by at least this many since the summary currently on file — below it, the recheck still refreshes userscore pills from the same stats sweep, but makes no LLM call')
ON CONFLICT (key) DO NOTHING;
