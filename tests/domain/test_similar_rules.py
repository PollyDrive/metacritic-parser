from __future__ import annotations

from metacritic_game_tracker.domain.rules import normalize_genres


def test_normalize_genres_dedupes_case_insensitively_keeping_first_casing():
    result = normalize_genres(["Action RPG", "action rpg", "RPG"])
    assert result == ["Action RPG", "RPG"]


def test_normalize_genres_strips_whitespace_and_drops_empties():
    result = normalize_genres([" Action RPG ", "", "  ", "RPG"])
    assert result == ["Action RPG", "RPG"]


def test_normalize_genres_empty_input_returns_empty_list():
    assert normalize_genres([]) == []


def test_normalize_genres_never_touches_a_catalog_or_database():
    # Purely a function of its input — no repository/session argument exists to accept.
    import inspect

    sig = inspect.signature(normalize_genres)
    assert set(sig.parameters) == {"raw_genres"}
