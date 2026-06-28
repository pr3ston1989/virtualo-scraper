"""HTTP client with rate limiting, retries, and random user agents."""

import asyncio
import random
from typing import Optional

import httpx
from fake_useragent import UserAgent
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from config import (
    MAX_RETRIES,
    REQUEST_DELAY_MAX,
    REQUEST_DELAY_MIN,
    RETRY_WAIT_MAX,
    RETRY_WAIT_MIN,
    TIMEOUT,
)

ua = UserAgent()


class RateLimitedClient:
    """Async HTTP client with built-in rate limiting and retry logic."""

    def __init__(self) -> None:
        self._client: Optional[httpx.AsyncClient] = None
        self._lock = asyncio.Lock()

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=TIMEOUT,
                follow_redirects=True,
                http2=True,
            )
        return self._client

    def _random_headers(self) -> dict:
        return {
            "User-Agent": ua.random,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.7,en;q=0.5",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
        }

    @retry(
        stop=stop_after_attempt(MAX_RETRIES),
        wait=wait_exponential(min=RETRY_WAIT_MIN, max=RETRY_WAIT_MAX),
        retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.TransportError)),
        reraise=True,
    )
    async def get(self, url: str) -> httpx.Response:
        """GET request with rate limiting and automatic retries."""
        async with self._lock:
            delay = random.uniform(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX)
            await asyncio.sleep(delay)

        client = await self._get_client()
        response = await client.get(url, headers=self._random_headers())
        response.raise_for_status()
        return response

    async def get_bytes(self, url: str) -> bytes:
        """Download binary content (e.g. cover images)."""
        response = await self.get(url)
        return response.content

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
