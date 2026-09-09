"""Plain httpx client for Metacritic — politeness, not anti-bot theatre (research.md §5).

Measured directly against the live site: a default client with a realistic UA gets
200 on every page this service reads. No TLS impersonation, no proxy rotation. The
one thing that must not be silent is a block: a 403/429 or a challenge interstitial
must be classified with its own reason_code and raised loudly, never parsed as
"this page had no games" (research.md §5, §14).
"""
from __future__ import annotations

import asyncio

import httpx

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

_BLOCK_STATUS_REASONS = {403: "http_403", 429: "http_429"}

_CHALLENGE_MARKERS = ("Just a moment", "cf-challenge", "cf-browser-verification")


class ScrapeBlockedError(Exception):
    def __init__(self, reason_code: str, status_code: int, url: str):
        self.reason_code = reason_code
        self.status_code = status_code
        self.url = url
        super().__init__(f"{reason_code} ({status_code}) fetching {url}")


class MetacriticClient:
    def __init__(
        self,
        http_client: httpx.AsyncClient,
        delay_seconds: float,
        max_retries: int,
        timeout_seconds: float,
    ):
        self._client = http_client
        self._delay = delay_seconds
        self._max_retries = max_retries
        self._timeout = timeout_seconds

    async def fetch(self, url: str) -> str:
        last_error: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                response = await self._client.get(
                    url, headers={"User-Agent": _USER_AGENT}, timeout=self._timeout
                )
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt < self._max_retries:
                    await asyncio.sleep(self._delay)
                continue

            if response.status_code in _BLOCK_STATUS_REASONS:
                raise ScrapeBlockedError(
                    _BLOCK_STATUS_REASONS[response.status_code], response.status_code, url
                )
            if any(marker in response.text for marker in _CHALLENGE_MARKERS):
                raise ScrapeBlockedError("challenge", response.status_code, url)

            response.raise_for_status()
            await asyncio.sleep(self._delay)
            return response.text

        assert last_error is not None
        raise last_error
