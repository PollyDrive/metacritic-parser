from __future__ import annotations

import json
from unittest.mock import AsyncMock

from metacritic_game_tracker.infrastructure.scraper.review_api import (
    fetch_platform_stats,
    fetch_review_sample,
    pick_best_platform,
)


def _page_json(total, quotes):
    return json.dumps({"data": {"totalResults": total, "items": [{"quote": q} for q in quotes]}})


def _stats_json(review_count, score=None):
    return json.dumps({"data": {"item": {"reviewCount": review_count, "score": score}}})


async def test_fetch_review_sample_paginates_across_multiple_pages_up_to_the_cap():
    """Real constraint: the server ignores `limit` and always returns at most
    10 items per call — reaching 20 needs 2 round trips, walking `offset`."""
    pages = {
        0: _page_json(47, [f"q{i}" for i in range(10)]),
        10: _page_json(47, [f"q{i}" for i in range(10, 20)]),
    }
    calls = []

    async def fetch_json(url):
        offset = int(url.split("offset=")[1].split("&")[0])
        calls.append(offset)
        return pages[offset]

    quotes, total = await fetch_review_sample(fetch_json, "elden-ring", "critic", "pc", cap=20)

    assert total == 47
    assert quotes == [f"q{i}" for i in range(20)]
    assert calls == [0, 10]


async def test_fetch_review_sample_url_is_scoped_to_the_given_platform():
    seen_urls = []

    async def fetch_json(url):
        seen_urls.append(url)
        return _page_json(1, ["q"])

    await fetch_review_sample(fetch_json, "valheim", "user", "pc", cap=1)

    assert "/platform/pc/" in seen_urls[0]


async def test_fetch_platform_stats_returns_review_count_and_score():
    fetch_json = AsyncMock(return_value=_stats_json(334, 8.6))

    stats = await fetch_platform_stats(fetch_json, "onimusha-way-of-the-sword", "user", "playstation-5")

    assert stats.review_count == 334
    assert stats.score == 8.6


async def test_pick_best_platform_selects_the_platform_with_the_most_reviews():
    """Real bug this fixes: reviews are split per platform on Metacritic, and
    a fixed default (effectively whichever platform Metacritic's unscoped
    endpoint happens to prefer) was being summarized regardless of where
    the actual review volume was."""
    stats_by_platform = {
        "playstation-5": _stats_json(334, 8.6),
        "pc": _stats_json(31, 9.3),
        "xbox-series-x": _stats_json(2, 5.0),
    }

    async def fetch_json(url):
        for slug, body in stats_by_platform.items():
            if f"/platform/{slug}/stats/" in url:
                return body
        raise AssertionError(f"unexpected url {url}")

    result = await pick_best_platform(
        fetch_json, "onimusha-way-of-the-sword", "user",
        ["PlayStation 5", "PC", "Xbox Series X"],
    )

    assert result.best_platform == "PlayStation 5"
    assert result.best_review_count == 334
    assert result.scores_by_platform == {"PlayStation 5": 8.6, "PC": 9.3, "Xbox Series X": 5.0}


async def test_pick_best_platform_breaks_ties_by_taking_the_first_listed():
    async def fetch_json(url):
        return _stats_json(10, 7.0)  # identical for every platform

    result = await pick_best_platform(fetch_json, "g", "critic", ["Xbox Series X", "PC", "PlayStation 5"])

    assert result.best_platform == "Xbox Series X"


async def test_pick_best_platform_skips_a_platform_whose_stats_call_fails():
    """One bad platform stats call must not sink the whole sweep — the
    remaining platforms still get compared normally."""
    async def fetch_json(url):
        if "/platform/pc/" in url:
            raise Exception("boom")
        if "/platform/playstation-5/" in url:
            return _stats_json(50, 8.0)
        return _stats_json(5, 6.0)

    result = await pick_best_platform(fetch_json, "g", "critic", ["PC", "PlayStation 5", "Xbox Series X"])

    assert result.best_platform == "PlayStation 5"
    assert "PC" not in result.scores_by_platform


async def test_pick_best_platform_returns_none_when_every_platform_call_fails():
    """Total API unavailability — the caller must be able to detect "no
    signal at all" distinctly from "every platform genuinely has 0 reviews"
    and fall back to the SSR page instead of picking a platform blindly."""
    async def fetch_json(url):
        raise Exception("boom")

    result = await pick_best_platform(fetch_json, "g", "critic", ["PC", "PlayStation 5"])

    assert result is None
