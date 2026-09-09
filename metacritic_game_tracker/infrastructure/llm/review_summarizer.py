"""Critic/user review summarization — separate LLM calls, sanitized input.

`llm_call` is injected so tests never make a real HTTP request (constitution:
AsyncMock reserved for external HTTP clients including the LLM provider). The
production implementation lives in `llm_client.py`.
"""
from __future__ import annotations

import json
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


def _build_prompt(quotes: list[str], audience: str) -> str:
    who = "critics" if audience == "critic" else "players"
    joined = "\n---\n".join(quotes)
    return (
        f"Below are review excerpts from {who} for a video game.\n"
        f"Summarize the most common points about what {who} like and dislike about it.\n"
        f"Group the points logically instead of listing every single detail.\n"
        f"Format the output STRICTLY as a JSON object with two keys: 'pros' and 'cons'.\n"
        f"Each key must contain an array of strings (the bullet points).\n"
        f"Do NOT wrap the JSON in markdown code blocks. Output ONLY valid JSON.\n\n"
        f"Example:\n"
        f"{{\n"
        f'  "pros": ["Great graphics", "Fun gameplay"],\n'
        f'  "cons": ["Short story"]\n'
        f"}}\n\n"
        f"{joined}"
    )


async def summarize_reviews(
    quotes: list[str], audience: Literal["critic", "user"], llm_call: LlmCall
) -> SummaryResult:
    sanitized = [truncate_to_limit(sanitize_input(q)) for q in quotes]
    prompt = _build_prompt(sanitized, audience)
    text, input_tokens, output_tokens, model = await llm_call(SIMPLE_ROUTE, prompt)

    text = text.strip()
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    try:
        parsed = json.loads(text)
        if "pros" not in parsed or "cons" not in parsed:
            raise ValueError("JSON missing pros or cons")
    except json.JSONDecodeError as e:
        raise ValueError(f"LLM returned invalid JSON: {text}") from e

    return SummaryResult(
        summary_text=text, input_tokens=input_tokens, output_tokens=output_tokens, model=model
    )
