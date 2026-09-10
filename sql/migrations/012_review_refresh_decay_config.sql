-- FR-010: the review-refresh decay curve's recheck intervals and cutoff age
-- must be adjustable without a code change, same as reviews.growth_threshold
-- already is (migration 011). domain/rules.py's calculate_next_refresh reads
-- these three instead of hardcoding 3/7/28 days.
-- FR-012/research.md §5: also never seeded — the per-tick cap that keeps a
-- backlog of due games from starving new-game discovery.
INSERT INTO runtime_config (key, value, value_type, min_value, max_value, description) VALUES
    ('review_refresh.recent_tier_days', '3', 'int', 1, 30,
     'Recheck interval, in days, for games under 1 week old (FR-004)'),
    ('review_refresh.mid_tier_days', '7', 'int', 1, 90,
     'Recheck interval, in days, for games 1-4 weeks old (FR-004)'),
    ('review_refresh.max_age_weeks', '4', 'int', 1, 52,
     'Age, in weeks, past which a game exits the review-refresh pass entirely (FR-004)'),
    ('review_refresh.games_per_run', '20', 'int', 1, 200,
     'Cap on games recheck-visited per worker tick, youngest-due first (FR-012)')
ON CONFLICT (key) DO NOTHING;
