"""HTTP clients for fetching Virtualo.pl pages.

Two backends are available (selected via config.CLIENT_TYPE):

* HttpxClient     - plain HTTP via httpx. No browser, low resource usage,
                    works on shared hosting. Default. Virtualo's product and
                    listing pages are server-rendered, so this is sufficient.
* PlaywrightClient - headless Firefox for full JS rendering. Needs system
                    resources and may fail on hosts with low process/thread
                    limits (RLIMIT_NPROC) — the classic "Resource temporarily
                    unavailable" / "creating thread 'gmain'" error.

Both expose the same interface used by the scraper:
    await client.get(url, wait_selector=None) -> PageResponse
    await client.get_bytes(url)               -> bytes
    await client.fetch_raw(url)               -> bytes
    client.stats                              -> dict
    await client.close()
"""

import asyncio
import logging
import random
from typing import Optional

from config import (
    CLIENT_TYPE,
    REQUEST_DELAY_MAX,
    REQUEST_DELAY_MIN,
    MAX_RETRIES,
    RETRY_WAIT_MIN,
    RETRY_WAIT_MAX,
    TIMEOUT,
)

logger = logging.getLogger(__name__)

# User agents to rotate
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
]


class PageResponse:
    """Response wrapper with an httpx-like interface."""

    def __init__(self, text: str, content: bytes, status_code: int, url: str):
        self.text = text
        self.content = content
        self.status_code = status_code
        self.url = url

    def raise_for_status(self):
        if self.status_code >= 400:
            raise PageError(f"HTTP {self.status_code}")


class PageError(Exception):
    """Error from fetching a page."""
    pass


# ---------------------------------------------------------------------------
# httpx-based client (default)
# ---------------------------------------------------------------------------


class HttpxClient:
    """Plain-HTTP client. No browser — ideal for constrained/shared hosting."""

    def __init__(self) -> None:
        import httpx  # local import so playwright-only setups don't need it

        self._httpx = httpx
        self._client: Optional["httpx.AsyncClient"] = None
        self._lock = asyncio.Lock()
        self._request_count = 0
        self._error_count = 0

    async def _ensure_client(self) -> "object":
        if self._client is None or self._client.is_closed:
            self._client = self._httpx.AsyncClient(
                timeout=TIMEOUT,
                follow_redirects=True,
                http2=True,
                headers={
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.7,en;q=0.5",
                },
            )
        return self._client

    def _headers(self) -> dict:
        return {"User-Agent": random.choice(USER_AGENTS)}

    async def _throttle(self) -> None:
        async with self._lock:
            await asyncio.sleep(random.uniform(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX))

    async def get(self, url: str, wait_selector: Optional[str] = None) -> PageResponse:
        """Fetch a page. `wait_selector` is accepted for API parity but unused."""
        await self._throttle()
        self._request_count += 1
        client = await self._ensure_client()

        last_exc: Optional[Exception] = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = await client.get(url, headers=self._headers())

                if resp.status_code == 429:
                    wait = min(RETRY_WAIT_MAX, RETRY_WAIT_MIN * attempt * 2)
                    logger.warning(f"Rate limited (429). Waiting {wait}s...")
                    await asyncio.sleep(wait)
                    continue

                if resp.status_code >= 400:
                    raise PageError(f"HTTP {resp.status_code} for {url}")

                self._error_count = 0
                return PageResponse(
                    text=resp.text,
                    content=resp.content,
                    status_code=resp.status_code,
                    url=url,
                )

            except (self._httpx.TransportError, self._httpx.TimeoutException, PageError) as e:
                last_exc = e
                self._error_count += 1
                if attempt < MAX_RETRIES:
                    wait = min(RETRY_WAIT_MAX, RETRY_WAIT_MIN * attempt)
                    logger.debug(f"  Retry {attempt}/{MAX_RETRIES} for {url} after {wait}s: {e}")
                    await asyncio.sleep(wait)

        raise PageError(f"Failed after {MAX_RETRIES} attempts: {url} ({last_exc})")

    async def fetch_raw(self, url: str) -> bytes:
        """Fetch raw bytes (sitemaps, gzipped XML, etc.)."""
        await self._throttle()
        self._request_count += 1
        client = await self._ensure_client()
        resp = await client.get(url, headers=self._headers())
        resp.raise_for_status()
        return resp.content

    async def get_bytes(self, url: str) -> bytes:
        """Download binary content (cover images)."""
        client = await self._ensure_client()
        try:
            resp = await client.get(url, headers=self._headers())
            if resp.status_code < 400:
                return resp.content
        except Exception as e:
            logger.debug(f"Binary download failed: {e}")
        return b""

    @property
    def stats(self) -> dict:
        return {"requests": self._request_count, "errors": self._error_count}

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
        self._client = None


# ---------------------------------------------------------------------------
# Playwright-based client (optional)
# ---------------------------------------------------------------------------


class PlaywrightClient:
    """Headless browser client for JS-rendered pages with rate limiting."""

    def __init__(self) -> None:
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._lock = asyncio.Lock()
        self._request_count = 0
        self._error_count = 0

    async def _ensure_browser(self):
        """Ensure browser is running and return the page."""
        if self._page and not self._page.is_closed():
            return self._page

        from playwright.async_api import async_playwright

        logger.info("Starting headless browser (Firefox)...")
        self._playwright = await async_playwright().start()
        # Hardened launch args help on restricted hosts (disable sandbox).
        # NOTE: this does NOT fix RLIMIT_NPROC (thread) limits on shared hosting.
        self._browser = await self._playwright.firefox.launch(
            headless=True,
            firefox_user_prefs={
                "media.autoplay.default": 5,
                "permissions.default.image": 2,  # don't load images (faster)
            },
        )
        self._context = await self._browser.new_context(
            user_agent=random.choice(USER_AGENTS),
            locale="pl-PL",
            viewport={"width": 1920, "height": 1080},
            java_script_enabled=True,
        )

        self._page = await self._context.new_page()
        self._page.set_default_timeout(TIMEOUT * 1000)
        return self._page

    async def get(self, url: str, wait_selector: Optional[str] = None) -> PageResponse:
        """Navigate to URL and return page content after JS rendering."""
        async with self._lock:
            await asyncio.sleep(random.uniform(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX))

        self._request_count += 1
        page = await self._ensure_browser()

        try:
            if self._request_count % 50 == 0:
                await self._refresh_context()
                page = await self._ensure_browser()

            response = await page.goto(url, wait_until="domcontentloaded")

            if response and response.status == 429:
                logger.warning("Rate limited (429). Waiting 60s...")
                await asyncio.sleep(60)
                self._error_count += 1
                response = await page.goto(url, wait_until="domcontentloaded")

            if response and response.status >= 400:
                self._error_count += 1
                raise PageError(f"HTTP {response.status} for {url}")

            if wait_selector:
                try:
                    await page.wait_for_selector(wait_selector, timeout=15000)
                except Exception:
                    pass

            try:
                await page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass

            content = await page.content()
            self._error_count = 0
            return PageResponse(
                text=content,
                content=content.encode("utf-8"),
                status_code=response.status if response else 200,
                url=url,
            )

        except Exception:
            self._error_count += 1
            if self._error_count >= 5:
                logger.warning("Too many errors, refreshing browser...")
                await self._refresh_context()
            raise

    async def fetch_raw(self, url: str) -> bytes:
        """Fetch raw bytes via the browser's request API (no JS rendering)."""
        page = await self._ensure_browser()
        response = await page.request.get(url)
        return await response.body()

    async def get_bytes(self, url: str) -> bytes:
        """Download binary content (covers)."""
        page = await self._ensure_browser()
        try:
            response = await page.request.get(url)
            return await response.body()
        except Exception as e:
            logger.debug(f"Binary download failed: {e}")
            return b""

    async def _refresh_context(self) -> None:
        """Close and recreate browser context (new identity)."""
        try:
            if self._page and not self._page.is_closed():
                await self._page.close()
            if self._context:
                await self._context.close()
        except Exception:
            pass
        self._page = None
        self._context = None
        self._error_count = 0
        logger.info("Browser context refreshed")

    @property
    def stats(self) -> dict:
        return {"requests": self._request_count, "errors": self._error_count}

    async def close(self) -> None:
        """Shut down the browser."""
        try:
            if self._page and not self._page.is_closed():
                await self._page.close()
            if self._context:
                await self._context.close()
            if self._browser:
                await self._browser.close()
            if self._playwright:
                await self._playwright.stop()
        except Exception as e:
            logger.debug(f"Browser cleanup: {e}")
        finally:
            self._page = None
            self._context = None
            self._browser = None
            self._playwright = None


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def make_client():
    """Create the configured HTTP client (see config.CLIENT_TYPE)."""
    if CLIENT_TYPE == "playwright":
        logger.info("Using Playwright (headless Firefox) client")
        return PlaywrightClient()
    logger.info("Using httpx client (no browser)")
    return HttpxClient()
