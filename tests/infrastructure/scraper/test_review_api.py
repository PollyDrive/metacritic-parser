from __future__ import annotations

import json

import pytest

from metacritic_game_tracker.infrastructure.scraper.review_api import (
    REVIEWS_PER_PAGE,
    ReviewApiShapeError,
    ReviewStats,
    parse_review_page,
    parse_review_stats,
    platform_url_slug,
    review_list_url,
    review_stats_url,
)


def _page(total, quotes):
    return json.dumps({
        "data": {
            "id": "x",
            "totalResults": total,
            "items": [{"quote": q, "score": 8, "author": "a"} for q in quotes],
        },
        "links": {},
        "meta": {},
    })


def _stats(review_count, score):
    return json.dumps({"data": {"item": {"reviewCount": review_count, "score": score, "max": 100}}})


def test_platform_url_slug_matches_metacritics_own_url_scheme():
    """Found live: Metacritic's own critic-reviews/user-reviews links use this
    exact slug scheme for the platform path segment."""
    assert platform_url_slug("PC") == "pc"
    assert platform_url_slug("PlayStation 5") == "playstation-5"
    assert platform_url_slug("Xbox Series X") == "xbox-series-x"
    assert platform_url_slug("Nintendo Switch 2") == "nintendo-switch-2"


def test_review_list_url_scopes_by_platform_via_a_path_segment_not_a_query_param():
    """Found live: a bare `?platform=xxx` query param on the un-scoped list
    endpoint is silently ignored (always returns one fixed default platform's
    reviews) — the platform has to be a PATH segment, matching the URL shape
    the SSR page's own internal fetch calls use."""
    url = review_list_url("valheim", "critic", "pc", offset=10)
    assert url == (
        "https://backend.metacritic.com/reviews/metacritic/critic/games/valheim"
        "/platform/pc/web?offset=10&limit=10&filterBySentiment=all&sort=score"
    )


def test_review_stats_url_targets_the_per_platform_aggregate_endpoint():
    url = review_stats_url("onimusha-way-of-the-sword", "user", "playstation-5")
    assert url == (
        "https://backend.metacritic.com/reviews/metacritic/user/games/"
        "onimusha-way-of-the-sword/platform/playstation-5/stats/web"
    )


def test_parse_review_page_extracts_total_and_quotes():
    page = parse_review_page(_page(93, ["Great game", "Loved it"]))
    assert page.total_reviews == 93
    assert page.quotes == ["Great game", "Loved it"]


def test_parse_review_page_skips_items_with_no_quote_text():
    text = json.dumps({
        "data": {"id": "x", "totalResults": 2, "items": [{"quote": "", "score": 8}, {"quote": "Good", "score": 9}]},
    })
    page = parse_review_page(text)
    assert page.quotes == ["Good"]


def test_parse_review_page_raises_a_typed_error_on_malformed_json():
    with pytest.raises(ReviewApiShapeError):
        parse_review_page("not json at all")


def test_parse_review_page_raises_a_typed_error_when_expected_keys_are_missing():
    """Gate-checked: an undocumented endpoint can change shape without notice —
    this must be a distinguishable failure the caller can fall back on, never
    a KeyError bubbling up raw."""
    with pytest.raises(ReviewApiShapeError):
        parse_review_page(json.dumps({"data": {"items": []}}))  # no totalResults


def test_parse_review_page_raises_when_total_reviews_is_not_an_integer():
    with pytest.raises(ReviewApiShapeError):
        parse_review_page(json.dumps({"data": {"totalResults": "ninety-three", "items": []}}))


def test_parse_review_stats_extracts_count_and_score():
    stats = parse_review_stats(_stats(334, 8.6))
    assert stats == ReviewStats(review_count=334, score=8.6)


def test_parse_review_stats_treats_a_null_review_count_as_zero():
    """Found live: an unrecognized/empty platform slug returns HTTP 200 with
    every stat field null, not an error — must degrade to 0, not crash or
    silently propagate None into a count comparison."""
    stats = parse_review_stats(_stats(None, None))
    assert stats == ReviewStats(review_count=0, score=None)


def test_parse_review_stats_raises_a_typed_error_on_malformed_json():
    with pytest.raises(ReviewApiShapeError):
        parse_review_stats("not json")


def test_parse_review_stats_raises_when_the_item_key_is_missing():
    with pytest.raises(ReviewApiShapeError):
        parse_review_stats(json.dumps({"data": {}}))


def test_reviews_per_page_matches_the_server_enforced_cap():
    """Documents the live-verified constraint: requesting `limit=50` in one
    call still returns only 10 items — pagination must walk `offset` in
    REVIEWS_PER_PAGE-sized steps to assemble a larger sample."""
    assert REVIEWS_PER_PAGE == 10
