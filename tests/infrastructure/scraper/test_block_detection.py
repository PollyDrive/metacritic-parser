from __future__ import annotations

import httpx
import pytest

from metacritic_game_tracker.infrastructure.scraper.metacritic_client import (
    MetacriticClient,
    ScrapeBlockedError,
)


def _client_with(handler) -> MetacriticClient:
    transport = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(transport=transport)
    return MetacriticClient(http_client, delay_seconds=0, max_retries=0, timeout_seconds=5)


async def test_403_response_raises_typed_error_with_its_own_reason_code():
    def handler(request):
        return httpx.Response(403, text="Forbidden")

    client = _client_with(handler)
    with pytest.raises(ScrapeBlockedError) as exc_info:
        await client.fetch("https://www.metacritic.com/game/x/")
    assert exc_info.value.reason_code == "http_403"


async def test_429_response_raises_typed_error_with_its_own_reason_code():
    def handler(request):
        return httpx.Response(429, text="Too Many Requests")

    client = _client_with(handler)
    with pytest.raises(ScrapeBlockedError) as exc_info:
        await client.fetch("https://www.metacritic.com/game/x/")
    assert exc_info.value.reason_code == "http_429"


async def test_200_challenge_interstitial_is_classified_as_blocked_not_empty_page():
    def handler(request):
        return httpx.Response(200, text="<html><title>Just a moment...</title></html>")

    client = _client_with(handler)
    with pytest.raises(ScrapeBlockedError) as exc_info:
        await client.fetch("https://www.metacritic.com/game/x/")
    assert exc_info.value.reason_code == "challenge"


async def test_normal_200_response_returns_the_page_text():
    def handler(request):
        return httpx.Response(200, text="<html>real content</html>")

    client = _client_with(handler)
    text = await client.fetch("https://www.metacritic.com/game/x/")
    assert text == "<html>real content</html>"
