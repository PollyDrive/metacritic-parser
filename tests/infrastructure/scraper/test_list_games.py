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


def test_site_header_navigation_links_are_not_mistaken_for_listing_results():
    """Real bug, caught live: Metacritic's site header carries a "New Releases"
    nav dropdown linking ~9 games. Those links sit on EVERY browse page, so
    scraping every /game/ href re-ingested the same 9 games on every run
    forever (9 wasted detail fetches per run, 130 update events across only 53
    distinct games) while the cursor kept paging. Only results-grid links count."""
    html = """
    <header>
      <ul class="c-site-header-navigation-list">
        <li><a class="c-site-header-navigation-list_item anchor" href="/game/valheim/">Valheim</a></li>
        <li><a class="c-site-header-navigation-list_item anchor" href="/game/orbitals/">Orbitals</a></li>
      </ul>
    </header>
    <main>
      <a class="c-finderProductCard_container" href="/game/deep-cut/">Deep Cut</a>
    </main>
    """
    assert [s.metacritic_slug for s in list_games(html)] == ["deep-cut"]
