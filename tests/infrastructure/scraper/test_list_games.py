from __future__ import annotations

from pathlib import Path

from metacritic_game_tracker.infrastructure.scraper.parser import list_games

FIXTURES = Path(__file__).parent / "fixtures"


def test_list_games_extracts_deduped_slugs_from_a_listing_page():
    html = (FIXTURES / "listing_page_new_releases.html").read_text()
    stubs = list_games(html)
    slugs = [s.metacritic_slug for s in stubs]
    assert slugs == [
        "valheim",
        "halloween-the-game",
        "hot-wheels-infinite-rush",
        "the-blood-of-dawnwalker",
        "onimusha-way-of-the-sword",
        "orbitals",
    ]


def test_list_games_returns_empty_list_not_an_error_when_page_has_zero_games():
    html = (FIXTURES / "listing_page_empty.html").read_text()
    assert list_games(html) == []
