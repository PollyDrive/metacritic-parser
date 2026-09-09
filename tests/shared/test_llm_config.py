from __future__ import annotations

from metacritic_game_tracker.shared.llm_config import REASONING_ROUTE, SIMPLE_ROUTE


def test_playthrough_route_uses_haiku_not_a_reasoning_model():
    """Kimi K2 Thinking was replaced with Haiku (2026-09-09): the takeaway is a
    short extractive summary, same shape as review summarization — reasoning
    doesn't pay for itself here, and a thinking model's hidden reasoning
    tokens make the effective cost per call unpredictable."""
    assert REASONING_ROUTE.model == SIMPLE_ROUTE.model == "claude-haiku-4-5"
