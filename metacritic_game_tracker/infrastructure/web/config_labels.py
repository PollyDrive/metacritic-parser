"""English labels and explanations for the settings page (contracts/web-ui.md,
US5) — the `runtime_config` seed rows themselves stay in English (the
canonical, technical description column); this is presentation-only
translation for the operator console, keyed by `runtime_config.key`."""
from __future__ import annotations

EN_LABELS: dict[str, str] = {
    "ingest.enabled": "Scheduled ingestion enabled",
    "ingest.games_per_run": "Games per run",
    "review_refresh.interval_hours": "Review refresh cadence, hours",
    "playthrough.interval_hours": "Playthrough cadence, hours",
    "scraper.request_delay_seconds": "Delay between requests, sec",
    "scraper.max_retries": "Max retries on failure",
    "scraper.timeout_seconds": "Request timeout, sec",
    "reviews.critic_sample_size": "Critic reviews for summary",
    "reviews.user_sample_size": "User reviews for summary",
    "enrichment.playthrough_enabled": "Enable YouTube playthrough search",
    "enrichment.youtube_daily_search_budget": "Daily YouTube search quota (1 search = 100 units)",
    "backfill.max_attempts": "Attempts before abandoning",
    "backfill.backoff_base_minutes": "Exponential backoff base, min",
    "dq.max_reject_ratio": "Rejection threshold to stop run",
    "reviews.growth_threshold": "Review growth to trigger re-summary",
    "review_refresh.recent_tier_days": "Recheck interval, games <1wk old (days)",
    "review_refresh.mid_tier_days": "Recheck interval, games 1-4wk old (days)",
    "review_refresh.max_age_weeks": "Refresh cutoff age (weeks)",
    "review_refresh.games_per_run": "Games rechecked per run",
    "enrichment.review_summary_enabled": "Enable review-summary generation",
}

# Explanations of why the setting is needed — one or two sentences longer than EN_LABELS,
# explaining the practical consequence of changing the value rather than just
# repeating the name.
EN_WHY: dict[str, str] = {
    "ingest.enabled": (
        "Master switch for scheduled ingestion of new games. Turn off to "
        "completely stop scraping Metacritic (e.g., for maintenance), "
        "without affecting other settings — the worker will continue running, but "
        "skip scheduled runs."
    ),
    "ingest.games_per_run": (
        "How many games are processed per run. Limits the batch "
        "load on the scraper and LLM API costs per execution."
    ),
    "review_refresh.interval_hours": (
        "How often the review-refresh backfill pass runs, independent of the "
        "ingest tick. Decayed TTL refreshes are only due every 3-7 days, so "
        "running this every hour (the old behavior) just produced empty runs."
    ),
    "playthrough.interval_hours": (
        "How often the playthrough backfill pass runs, independent of the "
        "ingest tick. The daily YouTube search budget is usually spent in one "
        "burst, so running this every hour (the old behavior) just produced "
        "empty runs once the budget was gone."
    ),
    "scraper.request_delay_seconds": (
        "Pause between requests to Metacritic. Reduces the risk of IP blocks "
        "for too frequent access — do not set to 0."
    ),
    "scraper.max_retries": (
        "How many times to retry a request on network error before "
        "considering the page unavailable and rejecting it."
    ),
    "scraper.timeout_seconds": (
        "How long to wait for a response from Metacritic per request before "
        "considering it timed out and retrying."
    ),
    "reviews.critic_sample_size": (
        "How many critic reviews are passed to the LLM for summarization. Capped "
        "at 10 — Metacritic's own review page never embeds more than 10 reviews "
        "per request, and paging (?page=N) is ignored, so a higher value here "
        "would never actually be reached."
    ),
    "reviews.user_sample_size": (
        "Same as above, but for user reviews — see 'Critic reviews for summary'."
    ),
    "enrichment.playthrough_enabled": (
        "Enables searching for playthroughs on YouTube and generating a takeaway "
        "for game cards. Requires a configured YOUTUBE_API_KEY in .env — without "
        "it, the playthrough pipeline will not run at all."
    ),
    "enrichment.review_summary_enabled": (
        "Enables generating critic/user review summaries — both for newly-ingested "
        "games and for the scheduled review-refresh pass. Off also stops refreshing "
        "userscore pills, since that piggybacks on the same source-site check. A "
        "manual 'Run now' for a specific pipeline still proceeds regardless of this "
        "switch."
    ),
    "enrichment.youtube_daily_search_budget": (
        "Daily limit of YouTube Data API 'units' for playthrough searches (a search "
        "costs 100 units per request). Protects the free Google quota from "
        "exhaustion during the day."
    ),
    "backfill.max_attempts": (
        "How many times to retry an enrichment attempt (review summary or "
        "playthrough) on failure before finally abandoning the game until "
        "manual intervention."
    ),
    "backfill.backoff_base_minutes": (
        "Base delay before retrying after an enrichment failure — "
        "grows exponentially with each subsequent failed attempt."
    ),
    "dq.max_reject_ratio": (
        "The ratio of rejected records in a single ingestion run that, "
        "when exceeded, aborts the entire run without advancing the pagination "
        "cursor — protection against mass scraper failure due to layout changes."
    ),
}

def label_for(key: str) -> str:
    return EN_LABELS.get(key, key)

def why_for(key: str) -> str:
    return EN_WHY.get(key, "")
