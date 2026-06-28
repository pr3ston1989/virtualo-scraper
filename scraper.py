"""Main scraper orchestrator for Virtualo.pl audiobooks."""

import asyncio
import logging
import re
from pathlib import Path
from typing import Optional

from config import BASE_URL, COVERS_DIR, SITEMAP_INDEX_URL
from db import get_session, init_db
from http_client import RateLimitedClient
from parsers import (
    ParsedAudiobook,
    parse_audiobook_page,
    parse_list_page,
    parse_sitemap,
    parse_sitemap_index,
)
from storage import enqueue_url, get_pending_urls, mark_done, mark_failed, save_audiobook

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


class VirtualoScraper:
    """Orchestrates the full scraping pipeline."""

    def __init__(self) -> None:
        self.client = RateLimitedClient()
        init_db()

    # ------------------------------------------------------------------
    # Phase 1: Discover audiobook URLs from sitemaps
    # ------------------------------------------------------------------

    async def discover_from_sitemap(self) -> int:
        """
        Fetch sitemap index, find audiobook-related sitemaps,
        and enqueue all audiobook URLs.

        Returns number of audiobook URLs enqueued.
        """
        logger.info("Fetching sitemap index...")
        response = await self.client.get(SITEMAP_INDEX_URL)
        sitemap_urls = parse_sitemap_index(response.text)
        logger.info(f"Found {len(sitemap_urls)} sub-sitemaps")

        # Filter to category sitemaps that may contain audiobooks
        # We'll process all category sitemaps since audiobooks appear across categories
        total_enqueued = 0

        session = get_session()
        try:
            for sitemap_url in sitemap_urls:
                enqueue_url(session, sitemap_url, "sitemap", priority=10)
            session.commit()
            logger.info(f"Enqueued {len(sitemap_urls)} sitemaps for processing")
        finally:
            session.close()

        # Process sitemaps
        total_enqueued = await self._process_sitemaps()
        return total_enqueued

    async def _process_sitemaps(self) -> int:
        """Download and parse all queued sitemaps, enqueue audiobook URLs."""
        total = 0
        session = get_session()
        try:
            while True:
                pending = get_pending_urls(session, "sitemap", limit=10)
                if not pending:
                    break

                for item in pending:
                    try:
                        logger.info(f"Processing sitemap: {item.url}")
                        response = await self.client.get(item.url)

                        # Detect if gzipped
                        is_gz = item.url.endswith(".gz")
                        content = response.content
                        urls = parse_sitemap(content, is_gzipped=is_gz)

                        # Filter audiobook URLs
                        audiobook_urls = [
                            u for u in urls if "/audiobook/" in u
                        ]

                        for url in audiobook_urls:
                            enqueue_url(session, url, "book", priority=5)
                            total += 1

                        mark_done(session, item)
                        session.commit()
                        logger.info(
                            f"  Found {len(audiobook_urls)} audiobook URLs "
                            f"(of {len(urls)} total)"
                        )

                    except Exception as e:
                        logger.warning(f"  Failed: {e}")
                        mark_failed(session, item, str(e))
                        session.commit()

        finally:
            session.close()

        logger.info(f"Total audiobook URLs enqueued: {total}")
        return total

    # ------------------------------------------------------------------
    # Phase 2: Discover from category listing pages
    # ------------------------------------------------------------------

    async def discover_from_listings(self, start_url: Optional[str] = None) -> int:
        """
        Crawl category listing pages to discover audiobook URLs.
        Falls back to sitemap-based discovery if no start URL provided.
        """
        if not start_url:
            start_url = f"{BASE_URL}/audiobooki/?sort_id=7"

        total = 0
        session = get_session()
        current_url: Optional[str] = start_url

        try:
            while current_url:
                logger.info(f"Crawling listing: {current_url}")
                try:
                    response = await self.client.get(current_url)
                    book_urls, next_page = parse_list_page(response.text)

                    for url in book_urls:
                        enqueue_url(session, url, "book", priority=5)
                        total += 1

                    session.commit()
                    logger.info(f"  Found {len(book_urls)} books, next: {next_page}")
                    current_url = next_page

                except Exception as e:
                    logger.warning(f"  Listing failed: {e}")
                    break

        finally:
            session.close()

        logger.info(f"Discovered {total} audiobooks from listings")
        return total

    # ------------------------------------------------------------------
    # Phase 3: Scrape individual audiobook pages
    # ------------------------------------------------------------------

    async def scrape_audiobooks(self, batch_size: int = 50) -> int:
        """
        Process queued audiobook URLs, parse detail pages,
        and save to database.

        Returns number of successfully scraped books.
        """
        scraped = 0
        session = get_session()

        try:
            while True:
                pending = get_pending_urls(session, "book", limit=batch_size)
                if not pending:
                    logger.info("No more audiobooks in queue.")
                    break

                logger.info(f"Processing batch of {len(pending)} audiobooks...")

                for item in pending:
                    try:
                        response = await self.client.get(item.url)
                        data = parse_audiobook_page(response.text, item.url)

                        if not data.title:
                            logger.warning(f"  No title found for {item.url}, skipping")
                            mark_failed(session, item, "No title parsed")
                            session.commit()
                            continue

                        # Download cover
                        if data.cover_url:
                            local_path = await self._download_cover(data.cover_url, item.url)
                            if local_path:
                                # We'll set this on the Book object via storage
                                pass

                        book = save_audiobook(session, data)

                        # Save cover path
                        if data.cover_url:
                            local_path = self._cover_path(item.url)
                            if local_path.exists():
                                book.cover_local_path = str(local_path)

                        mark_done(session, item)
                        session.commit()
                        scraped += 1

                        if scraped % 10 == 0:
                            logger.info(f"  Progress: {scraped} books scraped")

                    except Exception as e:
                        logger.warning(f"  Failed to scrape {item.url}: {e}")
                        mark_failed(session, item, str(e))
                        session.commit()

        finally:
            session.close()

        logger.info(f"Scraping complete. Total: {scraped} books saved.")
        return scraped

    # ------------------------------------------------------------------
    # Cover download
    # ------------------------------------------------------------------

    def _cover_path(self, book_url: str) -> Path:
        """Generate local file path for a cover image."""
        # Extract book ID from URL
        match = re.search(r"-i(\d+)", book_url)
        book_id = match.group(1) if match else book_url.split("/")[-1]
        return COVERS_DIR / f"{book_id}.jpg"

    async def _download_cover(self, cover_url: str, book_url: str) -> Optional[Path]:
        """Download cover image and save locally."""
        path = self._cover_path(book_url)
        if path.exists():
            return path

        try:
            data = await self.client.get_bytes(cover_url)
            path.write_bytes(data)
            logger.debug(f"  Cover saved: {path}")
            return path
        except Exception as e:
            logger.warning(f"  Cover download failed: {e}")
            return None

    # ------------------------------------------------------------------
    # Full pipeline
    # ------------------------------------------------------------------

    async def run(
        self,
        use_sitemap: bool = True,
        use_listings: bool = False,
        listing_url: Optional[str] = None,
    ) -> None:
        """
        Run the full scraping pipeline:
        1. Discover URLs (sitemap and/or listings)
        2. Scrape audiobook detail pages
        3. Save everything to database
        """
        try:
            if use_sitemap:
                await self.discover_from_sitemap()

            if use_listings:
                await self.discover_from_listings(listing_url)

            await self.scrape_audiobooks()

        finally:
            await self.client.close()

    async def close(self) -> None:
        await self.client.close()
