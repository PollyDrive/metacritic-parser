UPDATE runtime_config
SET value = '10', max_value = 10
WHERE key IN ('reviews.critic_sample_size', 'reviews.user_sample_size');
