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

# Client backend:
#   "httpx"      - plain HTTP, no browser (default; works on shared hosting,
#                  fast, low resource usage). Virtualo pages are server-rendered.
#   "playwright" - headless Firefox (needs system resources; may fail on shared
#                  hosting with low process/thread limits — see RLIMIT_NPROC).
CLIENT_TYPE = "httpx"
