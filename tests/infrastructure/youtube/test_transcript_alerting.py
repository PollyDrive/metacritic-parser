from __future__ import annotations

import pytest
from youtube_transcript_api._errors import RequestBlocked, TranscriptsDisabled

from metacritic_game_tracker.infrastructure.youtube import youtube_client


def test_a_video_without_captions_does_not_raise_an_alert(monkeypatch):
    """A playthrough video with no usable caption track is a normal, expected
    outcome (spec US4 AC-2, and it is already recorded as a `no_transcript`
    pipeline_reject) — not an operator alert. Emailing on it inverted FR-030:
    the operator got paged for routine misses while a real source-structure
    break (Gate A) sent nothing."""
    sent = []
    monkeypatch.setattr(
        youtube_client, "send_alert_email", lambda subject, body: sent.append(subject), raising=False
    )

    def no_captions(video_id):
        raise TranscriptsDisabled(video_id)

    monkeypatch.setattr(youtube_client, "_find_english_transcript", no_captions)

    assert youtube_client._fetch_transcript_sync("abc123") is None
    assert sent == []


def test_a_blocked_request_is_not_swallowed_as_no_transcript(monkeypatch):
    """Real bug: `RequestBlocked`/`IpBlocked` (YouTube rate-limiting or
    blocking this server's own outbound IP — a known, common failure mode for
    this library run from server infrastructure) both inherit from the same
    `CouldNotRetrieveTranscript` base as 'genuinely no captions track
    exists'. Catching the base class treated every such block as a normal
    'no transcript' and abandoned the game permanently — for a video that
    may well have real captions. Must propagate instead, so the caller's
    existing retry/backoff (application/backfill.py's process_game_step)
    handles it rather than a mislabeled permanent skip."""
    def blocked(video_id):
        raise RequestBlocked(video_id)

    monkeypatch.setattr(youtube_client, "_find_english_transcript", blocked)

    with pytest.raises(RequestBlocked):
        youtube_client._fetch_transcript_sync("abc123")
