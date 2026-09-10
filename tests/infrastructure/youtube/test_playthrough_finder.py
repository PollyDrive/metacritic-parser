from __future__ import annotations

from metacritic_game_tracker.infrastructure.youtube.playthrough_finder import (
    MAX_DURATION_SECONDS,
    MIN_DURATION_SECONDS,
    VideoCandidate,
    find_playthrough_candidates,
    rank_playthrough_candidates,
)

_MID_DURATION = (MIN_DURATION_SECONDS + MAX_DURATION_SECONDS) // 2


def _candidate(video_id, view_count, has_captions=True, duration_seconds=_MID_DURATION, description=""):
    return VideoCandidate(
        video_id=video_id,
        title=f"{video_id} review",
        view_count=view_count,
        has_captions=has_captions,
        duration_seconds=duration_seconds,
        description=description,
    )


def test_drops_uncaptioned_candidates_entirely():
    """We rely on the Data API's videoCaption=closedCaption filter to only
    return captioned results, but double-check client-side and strictly
    drop anything uncaptioned rather than wasting a fetch attempt on it."""
    a = _candidate("a", view_count=1000, has_captions=True)
    b = _candidate("b", view_count=50000, has_captions=False)

    ranked = rank_playthrough_candidates([a, b])

    assert [c.video_id for c in ranked] == ["a"]


def test_ranks_by_view_count_descending():
    a = _candidate("a", view_count=1000)
    b = _candidate("b", view_count=50000)
    c = _candidate("c", view_count=90000)

    ranked = rank_playthrough_candidates([a, b, c])

    assert [x.video_id for x in ranked] == ["c", "b", "a"]


def test_excludes_videos_longer_than_the_duration_cap():
    short = _candidate("short", view_count=100, duration_seconds=MAX_DURATION_SECONDS)
    long_ = _candidate("long", view_count=999999, duration_seconds=MAX_DURATION_SECONDS + 1)

    ranked = rank_playthrough_candidates([short, long_])

    assert [c.video_id for c in ranked] == ["short"]


def test_excludes_videos_shorter_than_the_duration_floor():
    """A short trailer/clip isn't a real playthrough — 3 minutes is the floor."""
    trailer = _candidate("trailer", view_count=999999, duration_seconds=MIN_DURATION_SECONDS - 1)
    real = _candidate("real", view_count=100, duration_seconds=MIN_DURATION_SECONDS)

    ranked = rank_playthrough_candidates([trailer, real])

    assert [c.video_id for c in ranked] == ["real"]


def test_returns_empty_when_every_candidate_exceeds_the_duration_cap():
    long_ = _candidate("long", view_count=999999, duration_seconds=MAX_DURATION_SECONDS + 1)

    assert rank_playthrough_candidates([long_]) == []


async def test_find_playthrough_candidates_returns_the_ranked_list_from_search():
    candidates = [_candidate("a", view_count=1000), _candidate("b", view_count=2000)]

    async def search_videos(query: str):
        return candidates

    result = await find_playthrough_candidates("Elden Ring", search_videos)

    assert [c.video_id for c in result] == ["b", "a"]


async def test_find_playthrough_candidates_searches_for_a_review_not_a_playthrough():
    """Review-style content is far more likely to carry real closed captions
    than a raw longplay VOD."""
    queries = []

    async def search_videos(query: str):
        queries.append(query)
        return []

    await find_playthrough_candidates("Elden Ring", search_videos)

    assert queries == ["Elden Ring review"]


async def test_find_playthrough_candidates_returns_empty_when_no_candidates_are_found():
    async def search_videos(query: str):
        return []

    result = await find_playthrough_candidates("Some Obscure Game", search_videos)

    assert result == []
