"""Production YouTube search + transcript fetch — the real HTTP implementation
behind playthrough_finder.py's injected `search_videos` and
application/playthrough.py's injected `get_transcript`.

Not unit tested (CLAUDE.md: LLM clients and live HTTP calls to Metacritic/YouTube
are excluded from the test suite — mirrors llm_client.py).

Search and view counts go through the official YouTube Data API v3 (search.list,
100 units; videos.list, 1 unit — tracked by YoutubeQuotaBudget). Caption text does
not go through the Data API at all: `captions.download` requires OAuth from the
video's own owner, so a single API key can never fetch someone else's subtitles.
Transcript text instead comes from `youtube-transcript-api`, which reads the same
public caption track the video page itself serves — free, and it spends none of
the daily search quota (research.md §6, T055). No audio-transcription fallback:
when no transcript is available, this alerts by email instead and moves on —
the takeaway is simply skipped for that game (backfill retries it later).
"""
from __future__ import annotations

import asyncio
import re

import httpx
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    AgeRestricted,
    InvalidVideoId,
    NoTranscriptFound,
    NotTranslatable,
    RequestBlocked,
    TranscriptsDisabled,
    TranslationLanguageNotAvailable,
    VideoUnavailable,
    VideoUnplayable,
)

from metacritic_game_tracker.infrastructure.youtube.playthrough_finder import VideoCandidate

_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
_VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"
_MAX_RESULTS = 10
# YouTube's own "Gaming" category — the query text alone (quoted title +
# "review") still ranks in reaction videos, news/announcement clips, and
# "top 10 games like X" listicles that happen to say the title; restricting
# to this category is a real API-side filter the query text can't express.
_GAMING_CATEGORY_ID = "20"

# YouTube video durations never carry a years/months/days component (the API
# caps a single upload's length well under a day) — just PT#H#M#S, any part optional.
_ISO8601_DURATION_RE = re.compile(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?")


def _parse_duration_seconds(iso8601: str) -> int:
    match = _ISO8601_DURATION_RE.fullmatch(iso8601)
    if not match:
        return 0
    hours, minutes, seconds = (int(g) if g else 0 for g in match.groups())
    return hours * 3600 + minutes * 60 + seconds


async def search_videos(
    query: str, http_client: httpx.AsyncClient, api_key: str
) -> list[VideoCandidate]:
    search_resp = await http_client.get(
        _SEARCH_URL,
        params={
            "part": "snippet",
            "q": query,
            "type": "video",
            "videoCategoryId": _GAMING_CATEGORY_ID,
            "videoDuration": "medium",
            "videoCaption": "closedCaption",
            "maxResults": _MAX_RESULTS,
            "key": api_key,
            "relevanceLanguage": "en",
        },
    )
    search_resp.raise_for_status()
    video_ids = [
        item["id"]["videoId"]
        for item in search_resp.json().get("items", [])
        if item.get("id", {}).get("videoId")
    ]
    if not video_ids:
        return []

    videos_resp = await http_client.get(
        _VIDEOS_URL,
        params={
            "part": "snippet,statistics,contentDetails",
            "id": ",".join(video_ids),
            "key": api_key,
        },
    )
    videos_resp.raise_for_status()

    return [
        VideoCandidate(
            video_id=item["id"],
            title=item["snippet"]["title"],
            view_count=int(item.get("statistics", {}).get("viewCount", 0)),
            has_captions=item.get("contentDetails", {}).get("caption") == "true",
            duration_seconds=_parse_duration_seconds(item.get("contentDetails", {}).get("duration", "PT0S")),
            description=item.get("snippet", {}).get("description", ""),
        )
        for item in videos_resp.json().get("items", [])
    ]


def _find_english_transcript(video_id: str):
    """`en`/`en-US` (manual, then generated) first; if the video only has
    captions in another language, fall back to that language's own
    translation into English when it offers one (its TRANSLATION LANGUAGES
    list includes "en")."""
    transcript_list = YouTubeTranscriptApi().list(video_id)
    try:
        return transcript_list.find_transcript(["en", "en-US"])
    except NoTranscriptFound:
        for transcript in transcript_list:
            if transcript.is_translatable and any(
                lang.language_code == "en" for lang in transcript.translation_languages
            ):
                return transcript.translate("en")
        raise


# Only these actually mean "this video has no obtainable transcript" — safe
# to record as a normal no_transcript reject and abandon permanently (spec
# US4 AC-2). `RequestBlocked`/`IpBlocked` and every other
# `CouldNotRetrieveTranscript` subclass are access/infrastructure failures
# (YouTube rate-limiting or blocking this server's own IP is common for this
# library run from server infra) — those must propagate as real errors so
# the caller's existing retry/backoff handles them, instead of permanently
# abandoning a video that may well have real captions.
class TranscriptAccessBlocked(Exception):
    """Wraps youtube_transcript_api's RequestBlocked/IpBlocked — an IP-wide
    condition, not a per-video one, so the caller must treat it as a
    run-wide stop signal (FindPlaythroughTakeawayUseCase.run) rather than a
    per-game retry/backoff case."""


_NO_TRANSCRIPT_EXCEPTIONS = (
    NoTranscriptFound,
    TranscriptsDisabled,
    VideoUnavailable,
    VideoUnplayable,
    AgeRestricted,
    InvalidVideoId,
    NotTranslatable,
    TranslationLanguageNotAvailable,
)


def _fetch_transcript_sync(video_id: str) -> str | None:
    try:
        transcript = _find_english_transcript(video_id).fetch()
    except _NO_TRANSCRIPT_EXCEPTIONS:
        # A normal, expected outcome (spec US4 AC-2) — the caller records it as
        # a `no_transcript` pipeline_reject. It is NOT an operator alert:
        # emailing here inverted FR-030, paging on routine misses while a real
        # source-structure break (Gate A) sent nothing.
        return None
    except RequestBlocked as exc:
        # Also catches IpBlocked (RequestBlocked subclass) — an IP-wide
        # condition, not this-video-specific, so the application layer must
        # not treat it like a normal per-video miss.
        raise TranscriptAccessBlocked(str(exc)) from exc
    return " ".join(snippet.text for snippet in transcript.snippets)


async def get_transcript(video_id: str) -> str | None:
    return await asyncio.to_thread(_fetch_transcript_sync, video_id)
