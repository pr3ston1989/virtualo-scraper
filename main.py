"""CLI entry point for the Virtualo.pl audiobook scraper."""

import argparse
import asyncio
import logging
import sys

from scraper import VirtualoScraper


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Virtualo.pl audiobook scraper",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  # Full run: discover via sitemaps + scrape all
  python main.py

  # Discover from sitemaps only (no scraping)
  python main.py --discover-only

  # Scrape already-queued books only
  python main.py --scrape-only

  # Discover from category listing pages
  python main.py --use-listings --listing-url "https://virtualo.pl/audiobooki/kryminal-i-sensacja-c216/"

  # Combine sitemap + listing discovery
  python main.py --use-listings
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
        "--use-sitemap",
        action="store_true",
        default=True,
        help="Discover audiobooks via sitemap (default: True)",
    )
    parser.add_argument(
        "--no-sitemap",
        action="store_true",
        help="Skip sitemap discovery",
    )
    parser.add_argument(
        "--use-listings",
        action="store_true",
        help="Also discover from category listing pages",
    )
    parser.add_argument(
        "--listing-url",
        type=str,
        default=None,
        help="Starting URL for listing crawl",
    )
    parser.add_argument(
        "--incremental",
        action="store_true",
        help="Only scrape new audiobooks (skip already-scraped URLs)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=50,
        help="Number of books to process per batch (default: 50)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable debug logging",
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    scraper = VirtualoScraper()

    async def _run():
        try:
            if args.scrape_only:
                await scraper.scrape_audiobooks(batch_size=args.batch_size)
            elif args.discover_only:
                use_sitemap = not args.no_sitemap
                if use_sitemap:
                    await scraper.discover_from_sitemap()
                if args.use_listings:
                    await scraper.discover_from_listings(args.listing_url)
            else:
                use_sitemap = not args.no_sitemap
                await scraper.run(
                    use_sitemap=use_sitemap,
                    use_listings=args.use_listings,
                    listing_url=args.listing_url,
                )
        finally:
            await scraper.close()

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        print("\nScraping interrupted by user.")
        sys.exit(0)


if __name__ == "__main__":
    main()
