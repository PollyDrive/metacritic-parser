from __future__ import annotations

from unittest.mock import MagicMock

from metacritic_game_tracker.domain.models import PlatformScore
from metacritic_game_tracker.infrastructure.db.models import GameORM, PlatformScoreORM
from metacritic_game_tracker.infrastructure.db.repositories import GameRepository
from metacritic_game_tracker.infrastructure.scraper.parser import ParsedGame


def _parsed(metacritic_id=1300501979, slug="elden-ring", title="Elden Ring") -> ParsedGame:
    return ParsedGame(
        metacritic_id=metacritic_id,
        metacritic_slug=slug,
        title=title, release_date=None,
        description="desc",
        developer="From Software",
        cover_image_url="/img.jpg",
        video_url="https://video",
        genres=["Action RPG"],
        platforms=[],
    )


def _mock_result(scalar_value):
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar_value
    return result


async def test_upsert_inserts_a_new_game_when_absent(mock_session):
    mock_session.execute.return_value = _mock_result(None)
    repo = GameRepository(mock_session)

    game, is_new = await repo.upsert(_parsed())

    assert is_new is True
    mock_session.add.assert_called_once()
    added = mock_session.add.call_args[0][0]
    assert isinstance(added, GameORM)
    assert added.metacritic_id == 1300501979
    assert added.metacritic_slug == "elden-ring"


async def test_upsert_updates_the_existing_row_when_present(mock_session):
    existing = GameORM(id=1, metacritic_id=1300501979, metacritic_slug="elden-ring", title="Old Title")
    mock_session.execute.return_value = _mock_result(existing)
    repo = GameRepository(mock_session)

    game, is_new = await repo.upsert(_parsed(title="Elden Ring"))

    assert is_new is False
    mock_session.add.assert_not_called()
    assert game.title == "Elden Ring"


async def test_upsert_updates_slug_in_place_rather_than_inserting_a_duplicate():
    """research.md §10: a changed slug for an existing metacritic_id is an
    attribute update, not a new game row."""
    from unittest.mock import AsyncMock

    session = AsyncMock()
    existing = GameORM(id=1, metacritic_id=1300501979, metacritic_slug="old-slug", title="Elden Ring")
    session.execute.return_value = _mock_result(existing)
    repo = GameRepository(session)

    game, is_new = await repo.upsert(_parsed(slug="elden-ring-remastered"))

    assert is_new is False
    session.add.assert_not_called()
    assert game.metacritic_slug == "elden-ring-remastered"
    assert game.id == 1


async def test_list_platforms_returns_distinct_platform_names_in_use(mock_session):
    result = MagicMock()
    result.scalars.return_value.all.return_value = ["PC", "PS5", "Xbox Series X"]
    mock_session.execute.return_value = result
    repo = GameRepository(mock_session)

    platforms = await repo.list_platforms()

    assert platforms == ["PC", "PS5", "Xbox Series X"]


async def test_upsert_platform_scores_adds_a_newly_released_platform_on_recrawl(mock_session):
    """Edge case (T071): a game gaining a new platform on re-crawl updates the
    existing row in place and only inserts the platform that's actually new."""
    game = GameORM(id=1, metacritic_id=1, metacritic_slug="elden-ring", title="Elden Ring")
    existing_pc = PlatformScoreORM(id=1, game_id=1, platform="PC", metascore=90, userscore=8.0)
    result = MagicMock()
    result.scalars.return_value.all.return_value = [existing_pc]
    mock_session.execute.return_value = result
    repo = GameRepository(mock_session)

    parsed = _parsed()
    parsed = ParsedGame(
        metacritic_id=parsed.metacritic_id,
        metacritic_slug=parsed.metacritic_slug,
        title=parsed.title,
        release_date=parsed.release_date,
        description=parsed.description,
        developer=parsed.developer,
        cover_image_url=parsed.cover_image_url,
        video_url=parsed.video_url,
        genres=parsed.genres,
        platforms=[
            PlatformScore(platform="PC", metascore=91, userscore=8.1),
            PlatformScore(platform="PlayStation 5", metascore=95, userscore=8.5),
        ],
    )

    await repo.upsert_platform_scores(game, parsed)

    assert existing_pc.metascore == 91  # updated in place, not duplicated
    mock_session.add.assert_called_once()
    added = mock_session.add.call_args[0][0]
    assert added.platform == "PlayStation 5"
