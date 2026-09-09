"""Client against OPENCODE_BASE_URL (OpenCode Zen), with the route's own
fallback chain (shared/llm_config.py) tried on failure.

OpenCode Zen splits by model family (docs: opencode.ai/docs/zen): Claude
models go through /messages in the Anthropic Messages API shape (x-api-key
auth, bare model id, `content[0].text` response); DeepSeek/MiniMax/GLM/Kimi
go through /chat/completions in the OpenAI-compatible shape (Authorization:
Bearer, `choices[0].message.content` response). Sending a claude-* model to
/chat/completions returns a 200 with a plain-text "Not Found" body.
"""
from __future__ import annotations

import os

import httpx

from metacritic_game_tracker.shared.llm_config import LLMRoute

_ANTHROPIC_VERSION = "2023-06-01"


async def call_llm(route: LLMRoute, prompt: str, http_client: httpx.AsyncClient) -> tuple[str, int, int, str]:
    base_url = os.environ["OPENCODE_BASE_URL"]
    is_anthropic = route.model.startswith("claude-")
    try:
        if is_anthropic:
            response = await http_client.post(
                f"{base_url}/messages",
                headers={
                    "x-api-key": os.environ["OPENCODE_API_KEY"],
                    "anthropic-version": _ANTHROPIC_VERSION,
                },
                json={
                    "model": route.model,
                    "temperature": route.temperature,
                    "max_tokens": route.max_tokens,
                    "messages": [{"role": "user", "content": prompt}],
                },
                timeout=route.timeout,
            )
            response.raise_for_status()
            data = response.json()
            text = data["content"][0]["text"]
            usage = data.get("usage", {})
            return text, usage.get("input_tokens", 0), usage.get("output_tokens", 0), route.model

        response = await http_client.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {os.environ['OPENCODE_API_KEY']}"},
            json={
                "model": route.model,
                "temperature": route.temperature,
                "max_tokens": route.max_tokens,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=route.timeout,
        )
        response.raise_for_status()
        data = response.json()
        text = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        return text, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0), route.model
    except (httpx.HTTPError, ValueError):
        if route.fallbacks:
            return await call_llm(route.fallbacks[0], prompt, http_client)
        raise
