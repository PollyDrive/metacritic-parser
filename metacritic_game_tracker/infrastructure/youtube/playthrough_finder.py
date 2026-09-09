"""Pick the most relevant playthrough candidate for a game title — the first
result by YouTube search's own relevance ranking.

`search_videos` is injected so this stays unit-testable without a real YouTube
Data API call — mirrors the fetch-injection pattern in application/ingest.py.
The production implementation lives in youtube_client.py.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

SEARCH_COST_UNITS = 100


@dataclass(frozen=True)
class VideoCandidate:
    video_id: str
    title: str
    view_count: int
    has_captions: bool


SearchVideos = Callable[[str], Awaitable[list[VideoCandidate]]]


async def find_most_relevant_playthrough(
    game_title: str, search_videos: SearchVideos
) -> VideoCandidate | None:
    candidates = await search_videos(f"{game_title} playthrough")
    if not candidates:
        return None
    return candidates[0]
