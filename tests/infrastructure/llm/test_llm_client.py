from __future__ import annotations

import os

import httpx

from metacritic_game_tracker.infrastructure.llm.llm_client import call_llm
from metacritic_game_tracker.shared.llm_config import LLMRoute

os.environ.setdefault("OPENCODE_API_KEY", "test-key")
os.environ.setdefault("OPENCODE_BASE_URL", "https://api.opencode.ai/zen/v1")


async def test_call_llm_returns_text_and_token_usage_on_success():
    def handler(request):
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "summary text"}}],
                "usage": {"prompt_tokens": 50, "completion_tokens": 20},
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    route = LLMRoute(model="m1", temperature=0.1, max_tokens=100, timeout=10)

    text, input_tokens, output_tokens, model = await call_llm(route, "prompt", client)

    assert text == "summary text"
    assert input_tokens == 50
    assert output_tokens == 20
    assert model == "m1"


async def test_call_llm_uses_the_anthropic_messages_shape_for_claude_models():
    """OpenCode Zen serves Claude models through /messages (Anthropic Messages
    API shape, x-api-key auth), not /chat/completions (OpenAI shape,
    Authorization: Bearer) — only DeepSeek/MiniMax/GLM/Kimi go through the
    OpenAI-compatible path. Sending a claude-* model to /chat/completions
    returns a 200 with a plain-text "Not Found" body, not JSON."""
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        captured["headers"] = request.headers
        return httpx.Response(
            200,
            json={
                "content": [{"type": "text", "text": "summary text"}],
                "usage": {"input_tokens": 50, "output_tokens": 20},
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    route = LLMRoute(model="claude-haiku-4-5", temperature=0.1, max_tokens=100, timeout=10)

    text, input_tokens, output_tokens, model = await call_llm(route, "prompt", client)

    assert text == "summary text"
    assert input_tokens == 50
    assert output_tokens == 20
    assert model == "claude-haiku-4-5"
    assert captured["url"].endswith("/messages")
    assert captured["headers"]["x-api-key"] == "test-key"
    assert "authorization" not in captured["headers"]
    assert captured["headers"]["anthropic-version"]


async def test_call_llm_falls_back_when_the_primary_model_fails():
    calls = []

    def handler(request):
        body = request.read()
        calls.append(body)
        if len(calls) == 1:
            return httpx.Response(500, text="server error")
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "fallback text"}}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 5},
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    route = LLMRoute(
        model="primary",
        temperature=0.1,
        max_tokens=100,
        timeout=10,
        fallbacks=[LLMRoute(model="fallback", temperature=0.1, max_tokens=100, timeout=10)],
    )

    text, _, _, model = await call_llm(route, "prompt", client)

    assert text == "fallback text"
    assert model == "fallback"
    assert len(calls) == 2
