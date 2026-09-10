from __future__ import annotations

from youtube_transcript_api._errors import CouldNotRetrieveTranscript

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
        raise CouldNotRetrieveTranscript(video_id)

    monkeypatch.setattr(youtube_client, "_find_english_transcript", no_captions)

    assert youtube_client._fetch_transcript_sync("abc123") is None
    assert sent == []
