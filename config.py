"""Scraper configuration."""

from pathlib import Path

# Database
DATABASE_URL = "sqlite:///virtualo.db"

# Directories
COVERS_DIR = Path("covers")
COVERS_DIR.mkdir(exist_ok=True)

# Scraping
BASE_URL = "https://virtualo.pl"
SITEMAP_INDEX_URL = "https://virtualo.pl/sitemap.xml"

# Rate limiting
REQUEST_DELAY_MIN = 1.0  # seconds between requests (minimum)
REQUEST_DELAY_MAX = 3.0  # seconds between requests (maximum)
MAX_RETRIES = 3
RETRY_WAIT_MIN = 5  # seconds
RETRY_WAIT_MAX = 30  # seconds

# Concurrency
MAX_CONCURRENT_REQUESTS = 3

# HTTP
TIMEOUT = 30  # seconds
