"""Metacritic's own review-listing JSON API (backend.metacritic.com) —
undocumented, found live: no API key required despite one being embedded in
the page's SSR payload for other purposes.

Reviews are split per platform on Metacritic (a game with 4 platform
releases has up to 4 independent review pools). The un-scoped endpoint
(`/games/{slug}/web`) silently ignores a `?platform=` query param and always
returns one fixed default platform's reviews — platform scoping only works
as a PATH segment (`/games/{slug}/platform/{platform_slug}/web`), matching
the URL shape the site's own critic-reviews/user-reviews pages use
internally (found by inspecting the SSR page's own embedded fetch calls).
There's also a `.../platform/{platform_slug}/stats/web` endpoint giving the
real aggregate score and review count for that one platform — this is what
actually populates a platform's userscore, not the fragile SSR
self-reference lookup used before.

Gate-checked: `parse_review_page`/`parse_review_stats` raise
`ReviewApiShapeError` on anything unrecognized, so the caller can fall back
to the SSR parser rather than trust a partially-parsed response.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

REVIEWS_PER_PAGE = 10


class ReviewApiShapeError(Exception):
    pass


@dataclass(frozen=True)
class ReviewPage:
    total_reviews: int
    quotes: list[str]


@dataclass(frozen=True)
class ReviewStats:
    review_count: int
    score: float | None


@dataclass(frozen=True)
class PlatformPick:
    best_platform: str
    best_review_count: int
    scores_by_platform: dict[str, float | None] = field(default_factory=dict)


def platform_url_slug(platform_name: str) -> str:
    """Matches Metacritic's own URL scheme, e.g. "PlayStation 5" -> "playstation-5"."""
    return platform_name.lower().replace(" ", "-")


def review_list_url(slug: str, audience: str, platform_slug: str, offset: int = 0, limit: int = REVIEWS_PER_PAGE) -> str:
    return (
        f"https://backend.metacritic.com/reviews/metacritic/{audience}/games/{slug}"
        f"/platform/{platform_slug}/web?offset={offset}&limit={limit}&filterBySentiment=all&sort=score"
    )


def review_stats_url(slug: str, audience: str, platform_slug: str) -> str:
    return (
        f"https://backend.metacritic.com/reviews/metacritic/{audience}/games/{slug}"
        f"/platform/{platform_slug}/stats/web"
    )


def parse_review_page(json_text: str) -> ReviewPage:
    try:
        payload = json.loads(json_text)
        data = payload["data"]
        total = data["totalResults"]
        items = data["items"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ReviewApiShapeError(f"unexpected review API response shape: {exc}") from exc

    if not isinstance(total, int) or not isinstance(items, list):
        raise ReviewApiShapeError("unexpected review API response types")

    quotes = [item["quote"] for item in items if isinstance(item, dict) and item.get("quote")]
    return ReviewPage(total_reviews=total, quotes=quotes)


def parse_review_stats(json_text: str) -> ReviewStats:
    try:
        payload = json.loads(json_text)
        item = payload["data"]["item"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ReviewApiShapeError(f"unexpected review stats response shape: {exc}") from exc

    if not isinstance(item, dict):
        raise ReviewApiShapeError("unexpected review stats response types")

    # An unrecognized/empty platform slug returns HTTP 200 with every field
    # null (found live) rather than an error — treat that as zero, not a
    # shape break.
    review_count = item.get("reviewCount") or 0
    score = item.get("score")
    return ReviewStats(review_count=review_count, score=score)


async def fetch_review_sample(
    fetch_json, slug: str, audience: str, platform_slug: str, cap: int
) -> tuple[list[str], int]:
    """Pull up to `cap` review quotes plus the true total review count for
    one platform.

    `fetch_json`: async (url: str) -> str (raw JSON body) — the injected HTTP
    boundary (a `MetacriticClient.fetch` in production, `AsyncMock` in tests).
    """
    quotes: list[str] = []
    total = 0
    offset = 0
    while len(quotes) < cap:
        page = parse_review_page(await fetch_json(review_list_url(slug, audience, platform_slug, offset)))
        total = page.total_reviews
        if not page.quotes:
            break
        quotes.extend(page.quotes)
        offset += REVIEWS_PER_PAGE
        if offset >= total:
            break
    return quotes[:cap], total


async def fetch_platform_stats(fetch_json, slug: str, audience: str, platform_slug: str) -> ReviewStats:
    return parse_review_stats(await fetch_json(review_stats_url(slug, audience, platform_slug)))


async def pick_best_platform(
    fetch_json, slug: str, audience: str, platform_names: list[str]
) -> PlatformPick | None:
    """Sweep every platform's review stats and pick the one with the most
    reviews (ties broken by list order — the first one wins). Returns the
    winner plus every OTHER platform's score too, so the caller can refresh
    all of a game's userscore pills from the same sweep at no extra cost —
    not just the one platform picked for summarization.

    Returns None only when EVERY platform's stats call failed — total API
    unavailability, distinct from "every platform genuinely has 0 reviews"
    (which still returns a pick, just with best_review_count == 0).
    """
    scores: dict[str, float | None] = {}
    best_platform: str | None = None
    best_count = -1
    any_succeeded = False

    for name in platform_names:
        try:
            stats = await fetch_platform_stats(fetch_json, slug, audience, platform_url_slug(name))
        except Exception:
            continue
        any_succeeded = True
        scores[name] = stats.score
        if stats.review_count > best_count:
            best_count = stats.review_count
            best_platform = name

    if not any_succeeded or best_platform is None:
        return None
    return PlatformPick(best_platform=best_platform, best_review_count=best_count, scores_by_platform=scores)
