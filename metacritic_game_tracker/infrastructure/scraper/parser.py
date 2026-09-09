"""Payload -> domain fields (research.md §9), plus listing-page candidate extraction
(§9.1) and review-subpage sampling.

Userscore note (research.md §4.1): Metacritic's own game-detail payload carries no
userscore at all; the only userscore we've found lives on a *different* embedded copy
of the same game (a self-referencing entry inside the "related-carousel" results) and
is a single title-level value, not per-platform. We apply that one value to every
platform row for the game — a documented simplification, not a per-platform measurement.
"""
from __future__ import annotations

import contextlib
import re
from dataclasses import dataclass
from datetime import date, datetime

from metacritic_game_tracker.domain.models import GameStub, PlatformScore
from metacritic_game_tracker.infrastructure.scraper.payload import extract_payload_array, resolve

_GAME_HREF_RE = re.compile(r'href="/game/([a-z0-9-]+)/"')


@dataclass(frozen=True)
class ParsedGame:
    metacritic_id: int
    metacritic_slug: str
    title: str
    release_date: date | None
    description: str | None
    developer: str | None
    cover_image_url: str | None
    video_url: str | None
    genres: list[str]
    platforms: list[PlatformScore]


def _find_game_root_index(array: list) -> int | None:
    for i, v in enumerate(array):
        if isinstance(v, dict) and {"criticScoreSummary", "platforms", "production"} <= v.keys():
            return i
    return None


def _find_title_userscore(array: list, metacritic_id: int) -> float | None:
    """Best-effort: some payloads embed a self-referencing copy of the game (inside
    the related-carousel results) that carries a title-level userScore. Absent is
    normal, not an error — treated the same as a "tbd" score."""
    for i, v in enumerate(array):
        if isinstance(v, dict) and v.get("id") == metacritic_id and "userScore" in v:
            resolved = resolve(array, i)
            score = (resolved.get("userScore") or {}).get("score")
            if score is not None:
                return float(score)
    return None


def get_resolved_game(html: str) -> dict | None:
    """Locate and resolve the main game dict from the payload — the input Gate A
    (research.md §14) validates before any field extraction happens."""
    array = extract_payload_array(html)
    root_index = _find_game_root_index(array)
    if root_index is None:
        return None
    resolved = resolve(array, root_index)
    userscore = _find_title_userscore(array, resolved["id"])
    resolved["_userscore"] = userscore
    return resolved


def build_parsed_game(game: dict) -> ParsedGame:
    """Pure transform: resolved game dict -> domain fields. Assumes Gate A already
    confirmed the required keys are present."""
    metacritic_id = game["id"]
    userscore = game.get("_userscore")

    release_date_str = game.get("releaseDate")
    release_date = None
    if release_date_str:
        with contextlib.suppress(ValueError):
            # E.g. "2022-02-25"
            release_date = datetime.strptime(release_date_str[:10], "%Y-%m-%d").date()

    developer = None
    for company in game.get("production", {}).get("companies", []):
        if company.get("typeName") == "Developer":
            developer = company.get("name")
            break

    cover_image_url = None
    for image in game.get("images", []):
        if image.get("typeName") == "mainImage":
            bucket_path = image.get("bucketPath")
            if bucket_path:
                cover_image_url = f"https://www.metacritic.com/a/img/catalog{bucket_path}"
            break

    video = game.get("video") or {}
    video_url = video.get("embedUrl")

    genres = [g["name"] for g in game.get("genres", []) if g.get("name")]

    platforms = [
        PlatformScore(
            platform=p["name"],
            metascore=(p.get("criticScoreSummary") or {}).get("score"),
            userscore=userscore,
        )
        for p in game.get("platforms", [])
    ]

    return ParsedGame(
        metacritic_id=metacritic_id,
        metacritic_slug=game["slug"],
        title=game["title"],
        release_date=release_date,
        description=game.get("description"),
        developer=developer,
        cover_image_url=cover_image_url,
        video_url=video_url,
        genres=genres,
        platforms=platforms,
    )


def parse_game_page(html: str) -> ParsedGame:
    resolved = get_resolved_game(html)
    if resolved is None:
        raise ValueError("No game data found in payload")
    return build_parsed_game(resolved)


def parse_reviews(html: str, sample_size: int) -> list[str]:
    """Extract up to `sample_size` review quotes from a `/critic-reviews/` or
    `/user-reviews/` page (research.md §8) — bounded sample for summarization input."""
    array = extract_payload_array(html)
    quotes: list[str] = []
    for i, v in enumerate(array):
        if len(quotes) >= sample_size:
            break
        if isinstance(v, dict) and {"quote", "score", "author"} <= v.keys():
            quote = resolve(array, i).get("quote")
            if quote:
                quotes.append(quote.strip())
    return quotes


def list_games(html: str) -> list[GameStub]:
    """Extract candidate games from a "New Releases" or "See All" listing page
    (research.md §9.1). Falls back to anchor-tag parsing when the listing page's
    payload doesn't carry a structured game array in the form we expect."""
    slugs: list[str] = []
    seen: set[str] = set()
    for match in _GAME_HREF_RE.finditer(html):
        slug = match.group(1)
        if slug not in seen:
            seen.add(slug)
            slugs.append(slug)
    return [GameStub(metacritic_slug=slug, metacritic_id=None) for slug in slugs]
