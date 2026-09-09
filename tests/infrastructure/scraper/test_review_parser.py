from __future__ import annotations

from pathlib import Path

from metacritic_game_tracker.infrastructure.scraper.parser import parse_reviews

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_reviews_extracts_critic_quotes_from_real_fixture():
    html = (FIXTURES / "game_critic_reviews_elden_ring.html").read_text()
    quotes = parse_reviews(html, sample_size=20)
    assert 1 <= len(quotes) <= 20
    assert any("FromSoftware" in q or "Elden Ring" in q for q in quotes)


def test_parse_reviews_extracts_user_quotes_from_real_fixture():
    html = (FIXTURES / "game_user_reviews_elden_ring.html").read_text()
    quotes = parse_reviews(html, sample_size=20)
    assert 1 <= len(quotes) <= 20


def test_parse_reviews_respects_the_sample_size_bound():
    html = (FIXTURES / "game_critic_reviews_elden_ring.html").read_text()
    quotes = parse_reviews(html, sample_size=3)
    assert len(quotes) <= 3
