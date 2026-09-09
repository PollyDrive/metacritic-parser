from __future__ import annotations

from sqlalchemy import inspect

from metacritic_game_tracker.infrastructure.db.models import (
    GameORM,
    PlatformScoreORM,
    PlaythroughTakeawayORM,
    ReviewSummaryORM,
)


def test_game_orm_declares_relationships_the_templates_render():
    """list.html/game_card.html read game.platform_scores, game.review_summaries,
    and game.playthrough_takeaway. Without a mapped relationship, GameRepository's
    plain `session.get`/`select(GameORM)` never populates them, and accessing the
    attribute raises AttributeError in production — only masked in tests that stub
    it manually onto a bare instance."""
    mapper = inspect(GameORM)
    rel_names = {r.key: r for r in mapper.relationships}

    assert "platform_scores" in rel_names
    assert rel_names["platform_scores"].mapper.class_ is PlatformScoreORM

    assert "review_summaries" in rel_names
    assert rel_names["review_summaries"].mapper.class_ is ReviewSummaryORM

    assert "playthrough_takeaway" in rel_names
    assert rel_names["playthrough_takeaway"].mapper.class_ is PlaythroughTakeawayORM
    assert rel_names["playthrough_takeaway"].uselist is False
