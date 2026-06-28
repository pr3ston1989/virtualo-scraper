"""HTTP client with rate limiting, retries, and random user agents."""

import asyncio
import logging
import random
from typing import Optional

import httpx
from fake_useragent import UserAgent
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    before_sleep_log,
)

from config import (
    MAX_RETRIES,
    REQUEST_DELAY_MAX,
    REQUEST_DELAY_MIN,
    RETRY_WAIT_MAX,
    RETRY_WAIT_MIN,
    TIMEOUT,
)

logger = logging.getLogger(__name__)
ua = UserAgent()


class RateLimitedClient:
    """Async HTTP client with built-in rate limiting and retry logic."""

    def __init__(self) -> None:
        self._client: Optional[httpx.AsyncClient] = None
        self._lock = asyncio.Lock()
        self._request_count = 0
        self._error_count = 0

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=TIMEOUT,
                follow_redirects=True,
                http2=True,
                limits=httpx.Limits(
                    max_connections=10,
                    max_keepalive_connections=5,
                    keepalive_expiry=30,
                ),
            )
        return self._client

    async def _refresh_client(self) -> None:
        """Close and recreate the client (e.g. after persistent errors)."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
        self._client = None
        logger.debug("HTTP client refreshed")

    def _random_headers(self) -> dict:
        return {
            "User-Agent": ua.random,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.7,en;q=0.5",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "DNT": "1",
        }

    @retry(
        stop=stop_after_attempt(MAX_RETRIES),
        wait=wait_exponential(min=RETRY_WAIT_MIN, max=RETRY_WAIT_MAX),
        retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.TransportError)),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    async def get(self, url: str) -> httpx.Response:
        """GET request with rate limiting and automatic retries."""
        async with self._lock:
            delay = random.uniform(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX)
            await asyncio.sleep(delay)

        client = await self._get_client()
        self._request_count += 1

        try:
            response = await client.get(url, headers=self._random_headers())
        except httpx.TransportError:
            self._error_count += 1
            # Refresh client after repeated transport errors
            if self._error_count >= 3:
                await self._refresh_client()
                self._error_count = 0
            raise

        # Handle rate limiting (429) with longer backoff
        if response.status_code == 429:
            retry_after = int(response.headers.get("Retry-After", "60"))
            logger.warning(f"Rate limited (429). Sleeping {retry_after}s...")
            await asyncio.sleep(retry_after)
            raise httpx.HTTPStatusError(
                "Rate limited",
                request=response.request,
                response=response,
            )

        # Handle server errors (5xx) — let tenacity retry
        if response.status_code >= 500:
            self._error_count += 1
            response.raise_for_status()

        # Handle 403/404 — don't retry, just raise
        if response.status_code in (403, 404):
            response.raise_for_status()

        # Success
        self._error_count = 0
        response.raise_for_status()
        return response

    async def get_bytes(self, url: str) -> bytes:
        """Download binary content (e.g. cover images)."""
        response = await self.get(url)
        return response.content

    @property
    def stats(self) -> dict:
        """Return request statistics."""
        return {
            "requests": self._request_count,
            "errors": self._error_count,
        }

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
