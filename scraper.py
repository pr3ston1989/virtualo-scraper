"""Main scraper orchestrator for Virtualo.pl audiobooks."""

import asyncio
import logging
import re
import signal
import time
from pathlib import Path
from typing import Optional

from config import BASE_URL, COVERS_DIR, SITEMAP_INDEX_URL
from db import get_session, init_db
from http_client import PlaywrightClient
from parsers import (
    ParsedAudiobook,
    parse_audiobook_page,
    parse_list_page,
    parse_sitemap,
    parse_sitemap_index,
)
from storage import (
    enqueue_url,
    enqueue_urls_batch,
    get_pending_urls,
    get_queue_stats,
    mark_done,
    mark_failed,
    reset_failed,
    save_audiobook,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# All audiobook category URLs on Virtualo.pl
# ---------------------------------------------------------------------------
AUDIOBOOK_CATEGORIES = [
    "https://virtualo.pl/audiobooki/asmr-c1112/",
    "https://virtualo.pl/audiobooki/audiokonferencje-c950/",
    "https://virtualo.pl/audiobooki/biografie-c288/",
    "https://virtualo.pl/audiobooki/biznes-c695/",
    "https://virtualo.pl/audiobooki/dla-dzieci-c598/",
    "https://virtualo.pl/audiobooki/dla-mlodziezy-c599/",
    "https://virtualo.pl/audiobooki/duchowosc-c275/",
    "https://virtualo.pl/audiobooki/edukacja-c266/",
    "https://virtualo.pl/audiobooki/eprasa-c1018/",
    "https://virtualo.pl/audiobooki/erotyka-c947/",
    "https://virtualo.pl/audiobooki/fantastyka-c291/",
    "https://virtualo.pl/audiobooki/historia-c276/",
    "https://virtualo.pl/audiobooki/horror-i-thriller-c943/",
    "https://virtualo.pl/audiobooki/humor-i-satyra-c927/",
    "https://virtualo.pl/audiobooki/jezyki-obce-c233/",
    "https://virtualo.pl/audiobooki/kryminal-i-sensacja-c216/",
    "https://virtualo.pl/audiobooki/lektury-szkolne-c1149/",
    "https://virtualo.pl/audiobooki/lektury-szkolne-c228/",
    "https://virtualo.pl/audiobooki/literatura-c596/",
    "https://virtualo.pl/audiobooki/literatura-faktu-c255/",
    "https://virtualo.pl/audiobooki/literatura-piekna-c212/",
    "https://virtualo.pl/audiobooki/nauki-humanistyczne-c601/",
    "https://virtualo.pl/audiobooki/nauki-scisle-c602/",
    "https://virtualo.pl/audiobooki/obcojezyczne-c907/",
    "https://virtualo.pl/audiobooki/obyczajowe-c236/",
    "https://virtualo.pl/audiobooki/opowiadania-c312/",
    "https://virtualo.pl/audiobooki/podcasty-c935/",
    "https://virtualo.pl/audiobooki/podroze-c320/",
    "https://virtualo.pl/audiobooki/poradniki-c213/",
    "https://virtualo.pl/audiobooki/powiesc-c310/",
    "https://virtualo.pl/audiobooki/prasa-c908/",
    "https://virtualo.pl/audiobooki/prawo-i-podatki-c552/",
    "https://virtualo.pl/audiobooki/publicystyka-c218/",
    "https://virtualo.pl/audiobooki/romans-c948/",
    "https://virtualo.pl/audiobooki/sluchowiska-c295/",
    "https://virtualo.pl/audiobooki/sport-i-rekreacja-c671/",
    "https://virtualo.pl/audiobooki/wakacje-i-podroze-c604/",
    "https://virtualo.pl/audiobooki/young-adult-c1115/",
]

# Additional listing sources
AUDIOBOOK_EXTRA_LISTINGS = [
    "https://virtualo.pl/audiobooki/nowosci/",
    "https://virtualo.pl/audiobooki/bestsellery/",
    "https://virtualo.pl/audiobooki/promocje/",
    "https://virtualo.pl/audiobooki/?sort_id=4",
]


class VirtualoScraper:
    """Orchestrates the full scraping pipeline."""

    def __init__(self) -> None:
        self.client = PlaywrightClient()
        init_db()
        self._seen_book_urls: set[str] = set()
        self._stop_requested = False
        self._start_time: float = 0
        self._stats = {
            "discovered": 0,
            "scraped": 0,
            "failed": 0,
            "skipped": 0,
        }

    def request_stop(self) -> None:
        """Signal the scraper to stop gracefully after current item."""
        self._stop_requested = True
        logger.info("Stop requested — finishing current item...")

    @property
    def should_stop(self) -> bool:
        return self._stop_requested

    # ------------------------------------------------------------------
    # Phase 1: Discover audiobook URLs from sitemaps
    # ------------------------------------------------------------------

    async def discover_from_sitemap(self) -> int:
        """Fetch sitemap index and enqueue audiobook URLs found."""
        if self.should_stop:
            return 0

        logger.info("Fetching sitemap index...")
        try:
            content = await self._fetch_raw(SITEMAP_INDEX_URL)
        except Exception as e:
            logger.error(f"Failed to fetch sitemap index: {e}")
            return 0

        sitemap_urls = parse_sitemap_index(content.decode("utf-8"))
        logger.info(f"Found {len(sitemap_urls)} sub-sitemaps")

        session = get_session()
        try:
            for sitemap_url in sitemap_urls:
                enqueue_url(session, sitemap_url, "sitemap", priority=10)
            session.commit()
        finally:
            session.close()

        total_enqueued = await self._process_sitemaps()
        return total_enqueued

    async def _fetch_raw(self, url: str) -> bytes:
        """Fetch raw bytes (for sitemaps/XML — no JS rendering needed)."""
        page = await self.client._ensure_browser()
        response = await page.request.get(url)
        return await response.body()

        session = get_session()
        try:
            for sitemap_url in sitemap_urls:
                enqueue_url(session, sitemap_url, "sitemap", priority=10)
            session.commit()
        finally:
            session.close()

        total_enqueued = await self._process_sitemaps()
        return total_enqueued

    async def _process_sitemaps(self) -> int:
        """Download and parse all queued sitemaps."""
        total = 0
        listing_urls_found: set[str] = set()
        session = get_session()
        try:
            while not self.should_stop:
                pending = get_pending_urls(session, "sitemap", limit=10)
                if not pending:
                    break

                for item in pending:
                    if self.should_stop:
                        break
                    try:
                        logger.info(f"Processing sitemap: {item.url}")
                        content = await self._fetch_raw(item.url)

                        is_gz = item.url.endswith(".gz")
                        urls = parse_sitemap(content, is_gzipped=is_gz)

                        # Direct audiobook product URLs
                        audiobook_urls = [u for u in urls if "/audiobook/" in u]
                        for url in audiobook_urls:
                            if url not in self._seen_book_urls:
                                enqueue_url(session, url, "book", priority=5)
                                self._seen_book_urls.add(url)
                                total += 1

                        # Listing URLs to crawl later
                        for u in urls:
                            if "/audiobooki/" in u:
                                listing_urls_found.add(u)

                        mark_done(session, item)
                        session.commit()
                        logger.info(
                            f"  Found {len(audiobook_urls)} product URLs "
                            f"(of {len(urls)} total)"
                        )

                    except Exception as e:
                        logger.warning(f"  Sitemap failed: {e}")
                        mark_failed(session, item, str(e))
                        session.commit()
        finally:
            session.close()

        # Crawl discovered listing pages
        if listing_urls_found and not self.should_stop:
            logger.info(f"Crawling {len(listing_urls_found)} listing pages from sitemaps...")
            for listing_url in sorted(listing_urls_found):
                if self.should_stop:
                    break
                found = await self._crawl_listing(listing_url, max_pages=0)
                total += found

        logger.info(f"Total from sitemaps: {total}")
        return total

    # ------------------------------------------------------------------
    # Phase 2: Discover from category listing pages (primary method)
    # ------------------------------------------------------------------

    async def discover_from_categories(self, incremental: bool = False) -> int:
        """Crawl all audiobook category listing pages with pagination."""
        if self.should_stop:
            return 0

        total = 0

        # Extra listings first (nowości catch newest items fast)
        logger.info("=== Crawling nowości / bestsellery / promocje ===")
        for url in AUDIOBOOK_EXTRA_LISTINGS:
            if self.should_stop:
                break
            found = await self._crawl_listing(url, max_pages=0, incremental=incremental)
            total += found

        # All categories
        logger.info(f"=== Crawling {len(AUDIOBOOK_CATEGORIES)} categories ===")
        for i, category_url in enumerate(AUDIOBOOK_CATEGORIES, 1):
            if self.should_stop:
                break
            logger.info(f"Category {i}/{len(AUDIOBOOK_CATEGORIES)}: {category_url}")
            found = await self._crawl_listing(category_url, max_pages=0, incremental=incremental)
            total += found

        self._stats["discovered"] = total
        logger.info(f"Total from categories: {total}")
        return total

    async def discover_from_listings(self, start_url: Optional[str] = None, max_pages: int = 0) -> int:
        """Crawl a single listing page chain."""
        if not start_url:
            start_url = f"{BASE_URL}/audiobooki/?sort_id=4"
        return await self._crawl_listing(start_url, max_pages=max_pages)

    async def _crawl_listing(
        self, start_url: str, max_pages: int = 0, incremental: bool = False
    ) -> int:
        """
        Crawl a paginated listing page.

        Args:
            start_url: Starting URL.
            max_pages: Max pages (0 = unlimited).
            incremental: Stop when page has no new URLs.
        """
        total = 0
        session = get_session()
        current_url: Optional[str] = start_url
        pages_crawled = 0
        consecutive_empty = 0  # Pages with no new items in a row

        try:
            while current_url and not self.should_stop:
                if max_pages and pages_crawled >= max_pages:
                    break

                logger.info(f"  Page {pages_crawled + 1}: {current_url}")
                try:
                    response = await self.client.get(
                        current_url, wait_selector='a[href*="/audiobook/"]'
                    )
                    book_urls, next_page = parse_list_page(response.text)

                    new_count = 0
                    for url in book_urls:
                        if url not in self._seen_book_urls:
                            enqueue_url(session, url, "book", priority=5)
                            self._seen_book_urls.add(url)
                            new_count += 1
                            total += 1

                    session.commit()
                    pages_crawled += 1

                    logger.info(
                        f"    {len(book_urls)} books ({new_count} new), "
                        f"next: {next_page is not None}"
                    )

                    # Empty page — end of listing
                    if not book_urls:
                        break

                    # Track consecutive pages with no new items
                    if new_count == 0:
                        consecutive_empty += 1
                    else:
                        consecutive_empty = 0

                    # Incremental: stop after 2 consecutive pages with no new items
                    # (not just 1, in case items shifted between pages)
                    if incremental and consecutive_empty >= 2:
                        logger.info("    Incremental: 2 pages with no new items, stopping.")
                        break

                    current_url = next_page

                except Exception as e:
                    logger.warning(f"    Listing page failed: {e}")
                    break

        finally:
            session.close()

        if total > 0:
            logger.info(f"  → {total} new audiobooks ({pages_crawled} pages)")
        return total

    # ------------------------------------------------------------------
    # Phase 3: Scrape individual audiobook pages
    # ------------------------------------------------------------------

    async def scrape_audiobooks(self, batch_size: int = 50) -> int:
        """Process queued audiobook URLs, parse and save."""
        scraped = 0
        failed = 0
        session = get_session()

        try:
            while not self.should_stop:
                pending = get_pending_urls(session, "book", limit=batch_size)
                if not pending:
                    logger.info("No more audiobooks in queue.")
                    break

                logger.info(f"Processing batch of {len(pending)} audiobooks...")

                for item in pending:
                    if self.should_stop:
                        break
                    try:
                        response = await self.client.get(
                            item.url, wait_selector="h1"
                        )
                        data = parse_audiobook_page(response.text, item.url)

                        if not data.title:
                            logger.warning(f"  No title: {item.url}")
                            mark_failed(session, item, "No title parsed")
                            session.commit()
                            failed += 1
                            continue

                        # Download cover (non-critical — don't fail the book)
                        if data.cover_url:
                            await self._download_cover(data.cover_url, item.url)

                        book = save_audiobook(session, data)

                        # Save cover path
                        if data.cover_url:
                            local_path = self._cover_path(item.url)
                            if local_path.exists():
                                book.cover_local_path = str(local_path)

                        mark_done(session, item)
                        session.commit()
                        scraped += 1

                        if scraped % 25 == 0:
                            logger.info(f"  Progress: {scraped} scraped, {failed} failed")

                    except Exception as e:
                        logger.warning(f"  Failed: {item.url} — {e}")
                        mark_failed(session, item, str(e))
                        session.commit()
                        failed += 1

                # Refresh session periodically to avoid stale connections
                session.close()
                session = get_session()

        finally:
            session.close()

        self._stats["scraped"] = scraped
        self._stats["failed"] = failed
        logger.info(f"Scraping complete: {scraped} saved, {failed} failed.")
        return scraped

    # ------------------------------------------------------------------
    # Retry failed items
    # ------------------------------------------------------------------

    async def retry_failed(self, batch_size: int = 50) -> int:
        """
        Retry items that previously failed (e.g. due to timeouts).
        Resets their status and re-runs scraping.
        """
        session = get_session()
        try:
            count = reset_failed(session, url_type="book", max_retries=5)
        finally:
            session.close()

        if count == 0:
            logger.info("No failed items to retry.")
            return 0

        logger.info(f"Retrying {count} previously failed items...")
        return await self.scrape_audiobooks(batch_size=batch_size)

    # ------------------------------------------------------------------
    # Cover download
    # ------------------------------------------------------------------

    def _cover_path(self, book_url: str) -> Path:
        """Generate local file path for a cover image."""
        match = re.search(r"-i(\d+)", book_url)
        book_id = match.group(1) if match else book_url.split("/")[-2]
        return COVERS_DIR / f"{book_id}.jpg"

    async def _download_cover(self, cover_url: str, book_url: str) -> Optional[Path]:
        """Download cover image. Failures are non-critical."""
        path = self._cover_path(book_url)
        if path.exists():
            return path

        try:
            data = await self.client.get_bytes(cover_url)
            if data and len(data) > 100:  # Sanity check — not an error page
                path.write_bytes(data)
                return path
        except Exception as e:
            logger.debug(f"  Cover failed ({book_url}): {e}")
        return None

    # ------------------------------------------------------------------
    # Full pipeline
    # ------------------------------------------------------------------

    async def run(
        self,
        use_sitemap: bool = False,
        use_categories: bool = True,
        use_listings: bool = False,
        listing_url: Optional[str] = None,
        incremental: bool = False,
        retry: bool = True,
    ) -> None:
        """
        Run the full scraping pipeline.

        Args:
            use_sitemap: Scan sitemaps (slow, low yield).
            use_categories: Crawl category pages (recommended).
            use_listings: Crawl a specific listing URL.
            listing_url: Starting URL for listing crawl.
            incremental: Stop early when no new items found.
            retry: Also retry previously failed items.
        """
        self._start_time = time.time()

        try:
            # Load known URLs for dedup
            self._load_known_urls()

            if use_sitemap and not self.should_stop:
                await self.discover_from_sitemap()

            if use_categories and not self.should_stop:
                await self.discover_from_categories(incremental=incremental)

            if use_listings and not self.should_stop:
                await self.discover_from_listings(listing_url)

            if not self.should_stop:
                await self.scrape_audiobooks()

            # Retry failed items from this and previous runs
            if retry and not self.should_stop:
                await self.retry_failed()

        finally:
            await self.client.close()
            self._print_summary()

    def _load_known_urls(self) -> None:
        """Load already-scraped book URLs into memory for fast dedup."""
        session = get_session()
        try:
            from sqlalchemy import select as sa_select
            from models import ScrapeQueue
            stmt = sa_select(ScrapeQueue.url).where(ScrapeQueue.type == "book")
            urls = session.execute(stmt).scalars().all()
            self._seen_book_urls.update(urls)
            if urls:
                logger.info(f"Loaded {len(urls)} known book URLs")
        finally:
            session.close()

    def _print_summary(self) -> None:
        """Print final summary of the scraping run."""
        elapsed = time.time() - self._start_time if self._start_time else 0
        minutes = int(elapsed // 60)
        seconds = int(elapsed % 60)

        session = get_session()
        try:
            stats = get_queue_stats(session)
        finally:
            session.close()

        logger.info("=" * 60)
        logger.info("  SCRAPING SUMMARY")
        logger.info("=" * 60)
        logger.info(f"  Duration: {minutes}m {seconds}s")
        logger.info(f"  HTTP requests: {self.client.stats['requests']}")
        logger.info(f"  New URLs discovered: {self._stats['discovered']}")
        logger.info(f"  Books scraped: {self._stats['scraped']}")
        logger.info(f"  Books failed: {self._stats['failed']}")
        if self.should_stop:
            logger.info("  Status: INTERRUPTED (graceful stop)")
        else:
            logger.info("  Status: COMPLETED")
        logger.info("-" * 60)
        logger.info("  Queue state:")
        for url_type, statuses in sorted(stats.items()):
            parts = [f"{s}={c}" for s, c in sorted(statuses.items())]
            logger.info(f"    {url_type}: {', '.join(parts)}")
        logger.info("=" * 60)

    async def close(self) -> None:
        await self.client.close()
