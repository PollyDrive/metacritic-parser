"""Data-quality gates as plain code — no rule-catalogue table (research.md §14).

Gate A (source conformance) aborts the whole run and logs CRITICAL: a broken
payload shape means the source changed, and the run must not advance the
pagination cursor (research.md §14.2). Gate B (record validity) verdicts one
record at a time: missing identifying fields -> reject; missing recoverable
fields -> admit-with-flag, queued through the same backfill path as a missing
review summary (research.md §14.3).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from metacritic_game_tracker.infrastructure.scraper.parser import ParsedGame

log = logging.getLogger(__name__)

_REQUIRED_SOURCE_KEYS = {"id", "title", "slug", "description", "platforms", "criticScoreSummary"}


class GateSourceError(Exception):
    pass


def check_source(resolved_game: dict | None) -> None:
    if resolved_game is None:
        log.critical("Gate A: no game data found in payload — source structure likely changed")
        raise GateSourceError("game root not found in payload")

    missing = _REQUIRED_SOURCE_KEYS - resolved_game.keys()
    if missing:
        log.critical("Gate A: payload missing required keys: %s", sorted(missing))
        raise GateSourceError(f"missing required keys: {sorted(missing)}")


@dataclass(frozen=True)
class RecordVerdict:
    admitted: bool
    reason_code: str | None = None
    recoverable_gaps: list[str] = field(default_factory=list)


_RECOVERABLE_FIELDS = ("description", "developer", "cover_image_url")


def check_record(parsed: ParsedGame) -> RecordVerdict:
    if not parsed.metacritic_id:
        return RecordVerdict(admitted=False, reason_code="missing_id")
    if not parsed.title:
        return RecordVerdict(admitted=False, reason_code="missing_title")
    if not parsed.platforms:
        return RecordVerdict(admitted=False, reason_code="missing_platform")

    gaps = [f for f in _RECOVERABLE_FIELDS if not getattr(parsed, f)]
    return RecordVerdict(admitted=True, recoverable_gaps=gaps)
