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

import httpx
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import CouldNotRetrieveTranscript, NoTranscriptFound

from metacritic_game_tracker.infrastructure.youtube.playthrough_finder import VideoCandidate

_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
_VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"
_MAX_RESULTS = 10


async def search_videos(
    query: str, http_client: httpx.AsyncClient, api_key: str
) -> list[VideoCandidate]:
    search_resp = await http_client.get(
        _SEARCH_URL,
        params={
            "part": "snippet",
            "q": query,
            "type": "video",
            "maxResults": _MAX_RESULTS,
            "key": api_key,
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


def _fetch_transcript_sync(video_id: str) -> str | None:
    try:
        transcript = _find_english_transcript(video_id).fetch()
    except CouldNotRetrieveTranscript:
        # A normal, expected outcome (spec US4 AC-2) — the caller records it as
        # a `no_transcript` pipeline_reject. It is NOT an operator alert:
        # emailing here inverted FR-030, paging on routine misses while a real
        # source-structure break (Gate A) sent nothing.
        return None
    return " ".join(snippet.text for snippet in transcript.snippets)


async def get_transcript(video_id: str) -> str | None:
    return await asyncio.to_thread(_fetch_transcript_sync, video_id)
