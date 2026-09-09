from __future__ import annotations

from metacritic_game_tracker.domain.models import PlatformScore
from metacritic_game_tracker.infrastructure.dq.gates import check_record
from metacritic_game_tracker.infrastructure.scraper.parser import ParsedGame


def _parsed(**overrides) -> ParsedGame:
    base = {
        "metacritic_id": 1,
        "metacritic_slug": "game",
        "title": "Game", "release_date": None,
        "description": "desc",
        "developer": "Dev",
        "cover_image_url": "/img.jpg",
        "video_url": "https://video",
        "genres": ["Action"],
        "platforms": [PlatformScore(platform="PC", metascore=80, userscore=8.0)],
    }
    base.update(overrides)
    return ParsedGame(**base)


def test_check_record_admits_a_complete_record():
    verdict = check_record(_parsed())
    assert verdict.admitted is True


def test_check_record_rejects_when_metacritic_id_missing():
    verdict = check_record(_parsed(metacritic_id=None))
    assert verdict.admitted is False
    assert verdict.reason_code == "missing_id"


def test_check_record_rejects_when_title_missing():
    verdict = check_record(_parsed(title=""))
    assert verdict.admitted is False
    assert verdict.reason_code == "missing_title"


def test_check_record_admits_but_flags_when_only_description_is_missing():
    """FR-028: recoverable fields missing -> still admitted, queued for re-extraction."""
    verdict = check_record(_parsed(description=None))
    assert verdict.admitted is True
    assert "description" in verdict.recoverable_gaps
