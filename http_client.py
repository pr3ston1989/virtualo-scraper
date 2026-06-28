"""HTTP client using Playwright headless browser for JS-rendered pages."""

import asyncio
import logging
import random
from typing import Optional

from playwright.async_api import async_playwright, Browser, BrowserContext, Page

from config import (
    REQUEST_DELAY_MAX,
    REQUEST_DELAY_MIN,
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


class PlaywrightClient:
    """Headless browser client for JS-rendered pages with rate limiting."""

    def __init__(self) -> None:
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._lock = asyncio.Lock()
        self._request_count = 0
        self._error_count = 0

    async def _ensure_browser(self) -> Page:
        """Ensure browser is running and return the page."""
        if self._page and not self._page.is_closed():
            return self._page

        logger.info("Starting headless browser (Firefox)...")
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.firefox.launch(
            headless=True,
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

    async def get(self, url: str, wait_selector: Optional[str] = None) -> "PageResponse":
        """
        Navigate to URL and return page content after JS rendering.

        Args:
            url: URL to navigate to.
            wait_selector: Optional CSS selector to wait for before returning.
        """
        async with self._lock:
            delay = random.uniform(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX)
            await asyncio.sleep(delay)

        self._request_count += 1
        page = await self._ensure_browser()

        try:
            # Rotate user agent occasionally
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

            # Wait for content to render
            if wait_selector:
                try:
                    await page.wait_for_selector(wait_selector, timeout=15000)
                except Exception:
                    pass  # Content might not have the selector, continue anyway

            # Wait for network to be mostly idle (JS finished loading data)
            try:
                await page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                # Timeout is OK — some pages have persistent connections
                pass

            content = await page.content()
            self._error_count = 0
            return PageResponse(
                text=content,
                content=content.encode("utf-8"),
                status_code=response.status if response else 200,
                url=url,
            )

        except Exception as e:
            self._error_count += 1
            if self._error_count >= 5:
                logger.warning("Too many errors, refreshing browser...")
                await self._refresh_context()
            raise

    async def get_bytes(self, url: str) -> bytes:
        """Download binary content (for covers — uses simple fetch, no JS needed)."""
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


class PageResponse:
    """Response wrapper mimicking httpx.Response interface."""

    def __init__(self, text: str, content: bytes, status_code: int, url: str):
        self.text = text
        self.content = content
        self.status_code = status_code
        self.url = url

    def raise_for_status(self):
        if self.status_code >= 400:
            raise PageError(f"HTTP {self.status_code}")


class PageError(Exception):
    """Error from page navigation."""
    pass
