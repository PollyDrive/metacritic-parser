"""Rank playthrough candidates for a game title, best first (FR-018: "its most
popular ... playthrough video") — the caller tries them in order and uses the
first one whose transcript actually fetches, since a captioned=true video can
still fail (stale/wrong metadata, region lock, subtitles disabled after the
fact) and transcript fetching costs no YouTube Data API quota.

`search_videos` is injected so this stays unit-testable without a real YouTube
Data API call — mirrors the fetch-injection pattern in application/ingest.py.
The production implementation lives in youtube_client.py.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

SEARCH_COST_UNITS = 100

# We constrain playthroughs to between 3 and 20 minutes to avoid wasting
# transcript tokens on hour-long videos or short trailers.
MIN_DURATION_SECONDS = 180
MAX_DURATION_SECONDS = 1200


@dataclass(frozen=True)
class VideoCandidate:
    video_id: str
    title: str
    view_count: int
    has_captions: bool
    duration_seconds: int
    description: str


SearchVideos = Callable[[str], Awaitable[list[VideoCandidate]]]


def rank_playthrough_candidates(candidates: list[VideoCandidate]) -> list[VideoCandidate]:
    """Best-first order: within the duration cap, captioned videos only,
    most-viewed first. We rely on the Data API filtering for captions, but
    this double-checks and strictly drops any uncaptioned results to prevent
    wasting fetch attempts."""
    eligible = [c for c in candidates if MIN_DURATION_SECONDS <= c.duration_seconds <= MAX_DURATION_SECONDS]
    captioned = sorted((c for c in eligible if c.has_captions), key=lambda c: c.view_count, reverse=True)
    return captioned


async def find_playthrough_candidates(
    game_title: str, search_videos: SearchVideos
) -> list[VideoCandidate]:
    candidates = await search_videos(f'"{game_title}" game review')
    return rank_playthrough_candidates(candidates)
