from __future__ import annotations

from pathlib import Path

from metacritic_game_tracker.infrastructure.scraper.parser import build_parsed_game, parse_game_page
from metacritic_game_tracker.infrastructure.scraper.payload import extract_payload_array, resolve

FIXTURES = Path(__file__).parent / "fixtures"


def _elden_ring_html() -> str:
    return (FIXTURES / "game_page_elden_ring.html").read_text()


def test_extract_payload_array_locates_the_nuxt_data_script():
    array = extract_payload_array(_elden_ring_html())
    assert isinstance(array, list)
    assert len(array) > 100


def test_resolve_dereferences_indexed_values_recursively():
    array = extract_payload_array(_elden_ring_html())
    root = next(
        i
        for i, v in enumerate(array)
        if isinstance(v, dict) and "criticScoreSummary" in v and "platforms" in v
    )
    resolved = resolve(array, root)
    assert resolved["title"] == "Elden Ring"
    assert resolved["slug"] == "elden-ring"
    assert isinstance(resolved["platforms"], list)


def test_parse_game_page_extracts_required_fields_from_real_fixture():
    game = parse_game_page(_elden_ring_html())
    assert game.metacritic_id == 1300501979
    assert game.metacritic_slug == "elden-ring"
    assert game.title == "Elden Ring"
    assert game.release_date is not None
    assert game.release_date.year == 2022
    assert game.description is not None and "Miyazaki" in game.description
    assert game.developer == "From Software"
    assert game.genres == ["Action RPG"]
    assert game.video_url is not None


def test_parse_game_page_captures_every_platform_with_its_own_metascore():
    game = parse_game_page(_elden_ring_html())
    names = {p.platform for p in game.platforms}
    assert names == {"Xbox One", "PC", "PlayStation 4", "Xbox Series X", "PlayStation 5"}
    ps5 = next(p for p in game.platforms if p.platform == "PlayStation 5")
    assert ps5.metascore == 96


def test_parse_game_page_treats_tbd_metascore_as_none_not_zero():
    game = parse_game_page(_elden_ring_html())
    xbox_one = next(p for p in game.platforms if p.platform == "Xbox One")
    assert xbox_one.metascore is None


def test_build_parsed_game_treats_a_missing_userscore_as_none_not_zero():
    """Edge case (T071): 'tbd' — absence — must never surface as 0."""
    game = {
        "id": 1,
        "slug": "some-game",
        "title": "Some Game",
        "platforms": [{"name": "PC", "criticScoreSummary": {"score": 80}}],
    }

    parsed = build_parsed_game(game)

    assert parsed.platforms[0].userscore is None


def test_build_parsed_game_handles_a_missing_video_link():
    """Edge case (T071): no video on the page — no crash, video_url is None."""
    game = {"id": 1, "slug": "some-game", "title": "Some Game", "platforms": []}

    parsed = build_parsed_game(game)

    assert parsed.video_url is None
