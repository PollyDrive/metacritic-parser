"""Critic/user review summarization — separate LLM calls, sanitized input.

`llm_call` is injected so tests never make a real HTTP request (constitution:
AsyncMock reserved for external HTTP clients including the LLM provider). The
production implementation lives in `llm_client.py`.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

from metacritic_game_tracker.shared.guardrail import sanitize_input, truncate_to_limit
from metacritic_game_tracker.shared.llm_config import SIMPLE_ROUTE, LLMRoute

LlmCall = Callable[[LLMRoute, str], Awaitable[tuple[str, int, int, str]]]


@dataclass(frozen=True)
class SummaryResult:
    summary_text: str
    input_tokens: int
    output_tokens: int
    model: str


def _build_prompt(audience: Literal["critic", "user"], quotes: list[str]) -> str:
    who = "critics" if audience == "critic" else "players"
    joined = "\n---\n".join(quotes)
    return (
        f"Below are review excerpts from {who} for a video game. "
        f"Based ONLY on these excerpts, summarize what {who} like and dislike about it.\n"
        f"Format the output strictly as a bulleted list of Pros and Cons, using standard dash bullets. Do NOT include any Markdown headers (like # Title).\n\n"
        f"{joined}"
    )


async def summarize_reviews(
    quotes: list[str], audience: Literal["critic", "user"], llm_call: LlmCall
) -> SummaryResult:
    sanitized = [truncate_to_limit(sanitize_input(q)) for q in quotes]
    prompt = _build_prompt(audience, sanitized)
    text, input_tokens, output_tokens, model = await llm_call(SIMPLE_ROUTE, prompt)
    return SummaryResult(
        summary_text=text, input_tokens=input_tokens, output_tokens=output_tokens, model=model
    )
