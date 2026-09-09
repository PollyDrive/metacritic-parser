from __future__ import annotations

from metacritic_game_tracker.infrastructure.youtube.playthrough_finder import (
    VideoCandidate,
    find_most_relevant_playthrough,
)


async def test_picks_the_first_candidate_by_youtube_search_relevance():
    candidates = [
        VideoCandidate(video_id="a", title="Elden Ring Full Playthrough", view_count=1000, has_captions=True),
        VideoCandidate(video_id="b", title="Elden Ring Longplay", view_count=50000, has_captions=False),
    ]

    async def search_videos(query: str):
        return candidates

    result = await find_most_relevant_playthrough("Elden Ring", search_videos)

    assert result.video_id == "a"


async def test_returns_none_when_no_candidates_are_found():
    async def search_videos(query: str):
        return []

    result = await find_most_relevant_playthrough("Some Obscure Game", search_videos)

    assert result is None
