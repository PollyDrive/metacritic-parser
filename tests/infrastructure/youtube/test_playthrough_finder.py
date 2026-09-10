from __future__ import annotations

from metacritic_game_tracker.infrastructure.youtube.playthrough_finder import (
    VideoCandidate,
    find_most_relevant_playthrough,
)


async def test_picks_the_most_viewed_candidate():
    """FR-018: "its most popular ... playthrough video" — the highest
    view_count among search results, not just the first one back."""
    candidates = [
        VideoCandidate(video_id="a", title="Elden Ring Full Playthrough", view_count=1000, has_captions=True),
        VideoCandidate(video_id="b", title="Elden Ring Longplay", view_count=50000, has_captions=False),
    ]

    async def search_videos(query: str):
        return candidates

    result = await find_most_relevant_playthrough("Elden Ring", search_videos)

    assert result.video_id == "b"


async def test_returns_none_when_no_candidates_are_found():
    async def search_videos(query: str):
        return []

    result = await find_most_relevant_playthrough("Some Obscure Game", search_videos)

    assert result is None
