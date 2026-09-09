from __future__ import annotations

from metacritic_game_tracker.infrastructure.web.config_labels import (
    RU_LABELS,
    RU_WHY,
    label_for,
    why_for,
)

# Mirrors the seeded keys in sql/migrations/005_runtime_config.sql — every
# operator-tunable key must have a Russian label, or the settings page falls
# back to the raw technical key for it.
SEEDED_KEYS = [
    "ingest.enabled",
    "ingest.runs_per_hour",
    "ingest.games_per_run",
    "ingest.active_hours_start",
    "ingest.active_hours_end",
    "ingest.timezone",
    "scraper.request_delay_seconds",
    "scraper.max_retries",
    "scraper.timeout_seconds",
    "reviews.critic_sample_size",
    "reviews.user_sample_size",
    "enrichment.playthrough_enabled",
    "enrichment.youtube_daily_search_budget",
    "backfill.max_attempts",
    "backfill.backoff_base_minutes",
    "dq.max_reject_ratio",
]


def test_every_seeded_config_key_has_a_russian_label():
    missing = [key for key in SEEDED_KEYS if key not in RU_LABELS]
    assert missing == []


def test_label_for_falls_back_to_the_raw_key_when_untranslated():
    assert label_for("some.unknown.key") == "some.unknown.key"


def test_label_for_returns_the_russian_label_when_known():
    assert label_for("ingest.games_per_run") == "Игр за один запуск"


def test_every_seeded_config_key_has_a_why_explanation():
    missing = [key for key in SEEDED_KEYS if key not in RU_WHY]
    assert missing == []


def test_why_for_falls_back_to_empty_string_when_untranslated():
    assert why_for("some.unknown.key") == ""


def test_why_for_returns_the_explanation_when_known():
    assert why_for("scraper.request_delay_seconds") != ""
