from __future__ import annotations

import logging

import pytest

from metacritic_game_tracker.infrastructure.dq.gates import GateSourceError, check_source

_VALID = {
    "id": 1,
    "title": "Game",
    "slug": "game",
    "description": "desc",
    "platforms": [],
    "criticScoreSummary": {},
}


def test_check_source_passes_when_all_required_keys_present():
    check_source(_VALID)  # no exception


def test_check_source_raises_and_logs_critical_when_a_required_key_is_missing(caplog):
    incomplete = dict(_VALID)
    del incomplete["criticScoreSummary"]

    with caplog.at_level(logging.CRITICAL):
        with pytest.raises(GateSourceError):
            check_source(incomplete)

    assert any(r.levelno == logging.CRITICAL for r in caplog.records)


def test_check_source_raises_when_the_game_root_was_not_found_at_all():
    with pytest.raises(GateSourceError):
        check_source(None)
