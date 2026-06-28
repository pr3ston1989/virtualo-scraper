"""CLI entry point for the Virtualo.pl audiobook scraper."""

import argparse
import asyncio
import logging
import signal
import sys
from pathlib import Path

from scraper import VirtualoScraper

# Log to both console and file
LOG_FILE = Path("scraper.log")


def setup_logging(verbose: bool = False) -> None:
    """Configure logging to console + rotating file."""
    level = logging.DEBUG if verbose else logging.INFO

    # Root logger
    root = logging.getLogger()
    root.setLevel(level)

    # Console handler
    console = logging.StreamHandler()
    console.setLevel(level)
    console.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    root.addHandler(console)

    # File handler (append mode — preserves history across runs)
    file_handler = logging.FileHandler(LOG_FILE, mode="a", encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    root.addHandler(file_handler)

    # Suppress noisy loggers
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Virtualo.pl audiobook scraper",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  # Full run (default: crawl all categories + scrape + retry failed)
  python main.py

  # Fast update (only pick up new audiobooks)
  python main.py --incremental

  # Only discover URLs (no scraping)
  python main.py --discover-only

  # Only scrape already-queued books
  python main.py --scrape-only

  # Retry previously failed items only
  python main.py --retry-only

  # Specific listing with pagination
  python main.py --listing-url "https://virtualo.pl/audiobooki/kryminal-i-sensacja-c216/"

  # Skip categories, use sitemap only
  python main.py --no-categories --use-sitemap
""",
    )

    parser.add_argument(
        "--discover-only",
        action="store_true",
        help="Only discover URLs (don't scrape detail pages)",
    )
    parser.add_argument(
        "--scrape-only",
        action="store_true",
        help="Only scrape already-queued audiobook URLs",
    )
    parser.add_argument(
        "--retry-only",
        action="store_true",
        help="Only retry previously failed items",
    )
    parser.add_argument(
        "--use-sitemap",
        action="store_true",
        help="Also scan sitemaps (slow, low yield)",
    )
    parser.add_argument(
        "--no-categories",
        action="store_true",
        help="Skip category page crawling",
    )
    parser.add_argument(
        "--listing-url",
        type=str,
        default=None,
        help="Crawl a specific listing URL (with pagination)",
    )
    parser.add_argument(
        "--incremental",
        action="store_true",
        help="Stop crawling when no new items found (fast update)",
    )
    parser.add_argument(
        "--no-retry",
        action="store_true",
        help="Don't retry previously failed items",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=50,
        help="Books per batch (default: 50)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable debug logging",
    )

    args = parser.parse_args()
    setup_logging(verbose=args.verbose)

    logger = logging.getLogger(__name__)
    logger.info("=" * 40)
    logger.info("Virtualo.pl scraper starting...")
    logger.info("=" * 40)

    scraper = VirtualoScraper()

    # Graceful shutdown on Ctrl+C
    def handle_signal(sig, frame):
        scraper.request_stop()

    signal.signal(signal.SIGINT, handle_signal)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, handle_signal)

    async def _run():
        try:
            if args.retry_only:
                scraper._load_known_urls()
                await scraper.retry_failed(batch_size=args.batch_size)
            elif args.scrape_only:
                await scraper.scrape_audiobooks(batch_size=args.batch_size)
            elif args.discover_only:
                scraper._load_known_urls()
                if args.use_sitemap:
                    await scraper.discover_from_sitemap()
                if not args.no_categories:
                    await scraper.discover_from_categories(incremental=args.incremental)
                if args.listing_url:
                    await scraper.discover_from_listings(args.listing_url)
            else:
                await scraper.run(
                    use_sitemap=args.use_sitemap,
                    use_categories=not args.no_categories,
                    use_listings=bool(args.listing_url),
                    listing_url=args.listing_url,
                    incremental=args.incremental,
                    retry=not args.no_retry,
                )
        finally:
            await scraper.close()

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        logger.info("Interrupted by user.")
        sys.exit(0)


if __name__ == "__main__":
    main()
