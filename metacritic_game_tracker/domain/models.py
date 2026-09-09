from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Literal


@dataclass(frozen=True)
class PlatformScore:
    platform: str
    metascore: int | None
    userscore: float | None


@dataclass(frozen=True)
class ReviewSummary:
    audience: Literal["critic", "user"]
    summary_text: str


@dataclass(frozen=True)
class GameStub:
    """A candidate found on a listing page — just enough to dedupe before fetching the detail page."""

    metacritic_slug: str
    metacritic_id: int | None


@dataclass
class Game:
    metacritic_id: int
    metacritic_slug: str
    title: str
    release_date: date | None = None
    cover_image_url: str | None = None
    developer: str | None = None
    description: str | None = None
    video_url: str | None = None
    genres: list[str] = field(default_factory=list)
    platform_scores: list[PlatformScore] = field(default_factory=list)
    review_summaries: list[ReviewSummary] = field(default_factory=list)
