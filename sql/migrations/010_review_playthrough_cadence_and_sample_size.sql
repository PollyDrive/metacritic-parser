-- review_refresh and playthrough get their own cadence, decoupled from
-- ingest's hourly tick (research.md §3 scheduling model): Decayed TTL
-- refreshes are due every 3-7 days and playthrough's daily YouTube budget
-- burns in one burst, so running them on every hourly ingest tick produced
-- runs that found nothing to do, every hour, forever.
INSERT INTO runtime_config (key, value, value_type, min_value, max_value, description) VALUES
    ('review_refresh.interval_hours',  '3', 'int', 1, 24, 'Cadence for the review-refresh backfill pass, independent of the ingest tick'),
    ('playthrough.interval_hours',     '3', 'int', 1, 24, 'Cadence for the playthrough backfill pass, independent of the ingest tick')
ON CONFLICT (key) DO NOTHING;

-- Metacritic's own review-list page embeds exactly 10 reviews in its SSR
-- payload regardless of `?page=N` (confirmed live: requesting page 2/3 of
-- Elden Ring's 1819 critic reviews returns the same 10 objects) — there is no
-- way to fetch more than 10 without a different, unimplemented source (the
-- undocumented backend.metacritic.com API). The old value of 20 was
-- unreachable: parse_reviews() would stop at whatever the payload contained,
-- which was never more than 10, so the config implied a depth the scraper
-- could never deliver.
UPDATE runtime_config SET
    value = '10',
    max_value = 10,
    description = 'Reviews fed to critic summarization — capped at 10: Metacritic''s SSR payload never embeds more than 10 reviews per page, and ?page=N is ignored (research.md §8)'
WHERE key = 'reviews.critic_sample_size';

UPDATE runtime_config SET
    value = '10',
    max_value = 10,
    description = 'Reviews fed to user summarization — same 10-review cap as critic reviews, see that setting'
WHERE key = 'reviews.user_sample_size';
