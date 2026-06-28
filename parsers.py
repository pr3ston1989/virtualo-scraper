"""HTML parsers for Virtualo.pl audiobook pages."""

import gzip
import re
from dataclasses import dataclass, field
from typing import Optional
from xml.etree import ElementTree as ET

from selectolax.parser import HTMLParser


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------


@dataclass
class ParsedAudiobook:
    """All data extracted from a single audiobook detail page."""

    url: str = ""
    title: str = ""
    description: Optional[str] = None
    authors: list[str] = field(default_factory=list)
    narrators: list[str] = field(default_factory=list)
    translators: list[str] = field(default_factory=list)
    publisher: Optional[str] = None
    category: Optional[str] = None
    breadcrumb: Optional[str] = None
    format: Optional[str] = None
    release_date: Optional[str] = None
    original_title: Optional[str] = None
    language: Optional[str] = None
    isbn: Optional[str] = None
    series: Optional[str] = None
    length_str: Optional[str] = None
    duration_minutes: Optional[int] = None
    avg_rating: Optional[float] = None
    rating_count: Optional[int] = None
    price: Optional[float] = None
    price_original: Optional[float] = None
    cover_url: Optional[str] = None
    sample_url: Optional[str] = None
    type: str = "Audiobook"
    reviews: list[dict] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Sitemap parsing
# ---------------------------------------------------------------------------

SITEMAP_NS = {"ns": "http://www.sitemaps.org/schemas/sitemap/0.9"}


def parse_sitemap_index(xml_content: str) -> list[str]:
    """Extract sitemap URLs from sitemap index XML."""
    root = ET.fromstring(xml_content)
    urls = []
    for sitemap in root.findall("ns:sitemap", SITEMAP_NS):
        loc = sitemap.find("ns:loc", SITEMAP_NS)
        if loc is not None and loc.text:
            urls.append(loc.text.strip())
    return urls


def parse_sitemap(xml_content: bytes, is_gzipped: bool = False) -> list[str]:
    """Extract URLs from a sitemap XML (optionally gzipped)."""
    if is_gzipped:
        xml_content = gzip.decompress(xml_content)
    root = ET.fromstring(xml_content)
    urls = []
    for url_elem in root.findall("ns:url", SITEMAP_NS):
        loc = url_elem.find("ns:loc", SITEMAP_NS)
        if loc is not None and loc.text:
            urls.append(loc.text.strip())
    return urls


# ---------------------------------------------------------------------------
# Audiobook detail page parser
# ---------------------------------------------------------------------------


def _text(node) -> Optional[str]:
    """Safely extract text from a selectolax node."""
    if node is None:
        return None
    t = node.text(strip=True)
    return t if t else None


def _parse_price(text: Optional[str]) -> Optional[float]:
    """Parse Polish price format like '39,09 zł' to float."""
    if not text:
        return None
    text = text.replace("\xa0", " ").strip()
    match = re.search(r"(\d+[,.]?\d*)", text.replace(",", "."))
    if match:
        return float(match.group(1))
    return None


def _parse_duration(length_str: Optional[str]) -> Optional[int]:
    """Convert duration string like '5h 23min' or '3 godz. 10 min' to minutes."""
    if not length_str:
        return None
    total = 0
    hours = re.search(r"(\d+)\s*(?:h|godz|godzin)", length_str, re.IGNORECASE)
    minutes = re.search(r"(\d+)\s*(?:min)", length_str, re.IGNORECASE)
    if hours:
        total += int(hours.group(1)) * 60
    if minutes:
        total += int(minutes.group(1))
    return total if total > 0 else None


def parse_audiobook_page(html: str, url: str) -> ParsedAudiobook:
    """Parse a Virtualo audiobook detail page and return structured data."""
    tree = HTMLParser(html)
    result = ParsedAudiobook(url=url)
    full_text = tree.html or ""

    # --- Title ---
    title_node = tree.css_first("h1")
    if title_node:
        raw_title = title_node.text(strip=True)
        raw_title = re.sub(r"\s*-\s*(audiobook|ebook).*$", "", raw_title, flags=re.IGNORECASE)
        result.title = raw_title.strip()

    # --- Breadcrumb (schema.org BreadcrumbList) ---
    breadcrumb_spans = tree.css('ul.breadcrumb span[itemprop="name"]')
    if breadcrumb_spans:
        parts = [_text(s) for s in breadcrumb_spans if _text(s)]
        result.breadcrumb = " > ".join(parts)
        # Last part = deepest category
        if len(parts) >= 2:
            result.category = parts[-1]

    # --- Key-value pairs from "designation" divs ---
    designation_pairs = re.findall(
        r'<div class="designation">(.*?)</div>\s*<div class="data">(.*?)</div>',
        full_text,
        re.DOTALL,
    )
    for label_html, value_html in designation_pairs:
        label = HTMLParser(label_html).text(strip=True).rstrip(":")
        value_tree = HTMLParser(value_html)
        value = value_tree.text(strip=True) if value_tree.body else ""

        if "Wydawnictwo" in label:
            if not result.publisher:
                result.publisher = value
        elif "Lektor" in label:
            names = [n.strip() for n in value.split(",") if n.strip()]
            for n in names:
                if n not in result.narrators:
                    result.narrators.append(n)
        elif "Tłumacz" in label or "tlumacz" in label.lower():
            names = [n.strip() for n in value.split(",") if n.strip()]
            for n in names:
                if n not in result.translators:
                    result.translators.append(n)
        elif "Format" in label and not result.format:
            result.format = value.strip()
        elif "Data wydania" in label:
            result.release_date = value.strip()
        elif "Czas" in label:
            result.length_str = value.strip()
            result.duration_minutes = _parse_duration(result.length_str)
        elif "Seria" in label or "Cykl" in label:
            result.series = value.strip()
        elif "ISBN" in label:
            result.isbn = value.strip()
        elif "Język" in label or "Jezyk" in label:
            result.language = value.strip()

    # --- Authors ---
    author_links = tree.css('a[href*="/autor/"]')
    seen_authors = set()
    for link in author_links:
        name = link.text(strip=True)
        if name and name not in seen_authors:
            result.authors.append(name)
            seen_authors.add(name)

    # --- Narrators (fallback from links if not found via designation) ---
    if not result.narrators:
        narrator_links = tree.css('a[href*="-l"]')
        seen_narrators: set = set()
        for link in narrator_links:
            href = link.attributes.get("href", "")
            name = link.text(strip=True)
            if re.search(r"-l\d+/?$", href) and name and name not in seen_narrators:
                result.narrators.append(name)
                seen_narrators.add(name)

    # --- Translators (fallback from links) ---
    if not result.translators:
        translator_links = tree.css('a[href*="-t"]')
        seen_translators: set = set()
        for link in translator_links:
            href = link.attributes.get("href", "")
            name = link.text(strip=True)
            if re.search(r"-t\d+/?$", href) and name and name not in seen_translators:
                result.translators.append(name)
                seen_translators.add(name)

    # --- Publisher (fallback from links) ---
    if not result.publisher:
        publisher_links = tree.css('a[href*="-p"]')
        for link in publisher_links:
            href = link.attributes.get("href", "")
            name = link.text(strip=True)
            if re.search(r"-p\d+/?$", href) and name:
                result.publisher = name
                break

    # --- Product details table (second table with ISBN, language, etc.) ---
    detail_pairs = re.findall(
        r'product-details__title">(.*?)</td>\s*<td[^>]*>(.*?)</td>',
        full_text,
        re.DOTALL,
    )
    for label_html, value_html in detail_pairs:
        label = re.sub(r"<[^>]+>", "", label_html).strip().rstrip(":")
        value = re.sub(r"<[^>]+>", "", value_html).strip()

        if "ISBN" in label and not result.isbn:
            result.isbn = value
        elif "zyk" in label and not result.language:  # Język
            result.language = value
        elif "Kategoria" in label and not result.category:
            result.category = value

    # --- Release date from meta itemprop ---
    if not result.release_date:
        date_meta = tree.css_first('meta[itemprop="datePublished"]')
        if date_meta:
            result.release_date = date_meta.attributes.get("content")

    # --- Description ---
    # Primary: product-description-wrapper (the actual book description)
    desc_wrapper = tree.css_first('[class*="product-description-wrapper"]')
    if desc_wrapper:
        desc_text = desc_wrapper.text(strip=True)
        if desc_text and len(desc_text) > 20:
            result.description = desc_text

    # Fallback: itemprop="description"
    if not result.description:
        itemprop_desc = tree.css_first('[itemprop="description"]')
        if itemprop_desc:
            desc_text = itemprop_desc.text(strip=True)
            if desc_text and len(desc_text) > 20:
                result.description = desc_text

    # Fallback: meta og:description or meta description
    if not result.description:
        for selector in ['meta[property="og:description"]', 'meta[name="description"]']:
            meta_desc = tree.css_first(selector)
            if meta_desc:
                content = meta_desc.attributes.get("content", "")
                if content and len(content) > 30:
                    result.description = content
                    break

    # --- Prices ---
    # Only count prices explicitly in PLN (złotych), exclude "pkt" (points)
    price_matches = re.findall(
        r"(\d{1,3}[,.]\d{2})\s*(?:<[^>]*>)?\s*(?:zł|PLN)",
        full_text,
        re.IGNORECASE,
    )
    prices_zl = set()
    for pm in price_matches:
        val = float(pm.replace(",", "."))
        if 0 < val < 1000:  # sanity check
            prices_zl.add(val)

    # Also check itemprop="price"
    price_meta = tree.css_first('[itemprop="price"]')
    if price_meta:
        content = price_meta.attributes.get("content") or price_meta.text(strip=True)
        if content:
            try:
                prices_zl.add(float(content.replace(",", ".")))
            except ValueError:
                pass

    if prices_zl:
        sorted_prices = sorted(prices_zl)
        result.price = sorted_prices[0]
        if len(sorted_prices) > 1:
            result.price_original = sorted_prices[-1]

    # --- Rating ---
    rating_node = tree.css_first('[itemprop="ratingValue"]')
    if rating_node:
        val = rating_node.attributes.get("content") or rating_node.text(strip=True)
        if val:
            try:
                result.avg_rating = float(val.replace(",", "."))
            except ValueError:
                pass

    count_node = tree.css_first('[itemprop="ratingCount"], [itemprop="reviewCount"]')
    if count_node:
        val = count_node.attributes.get("content") or count_node.text(strip=True)
        if val:
            try:
                result.rating_count = int(re.sub(r"\D", "", val))
            except ValueError:
                pass

    # Fallback: regex
    if result.avg_rating is None:
        rating_match = re.search(
            r"(\d+[.,]\d+)\s*/\s*\d+|ratingValue[\":\s]+(\d+[.,]\d+)",
            full_text,
        )
        if rating_match:
            val = rating_match.group(1) or rating_match.group(2)
            if val:
                result.avg_rating = float(val.replace(",", "."))

    if result.rating_count is None:
        count_match = re.search(r"ratingCount[\":\s]+(\d+)|(\d+)\s*ocen", full_text)
        if count_match:
            val = count_match.group(1) or count_match.group(2)
            if val:
                result.rating_count = int(val)

    # --- Cover URL ---
    # Prefer large cover
    cover_node = tree.css_first('img[src*="covers/large"]')
    if not cover_node:
        cover_node = tree.css_first('img[src*="cloud-cdn.virtualo"]')
    if cover_node:
        result.cover_url = cover_node.attributes.get("src")

    # Fallback: og:image (upgrade small to large)
    if not result.cover_url:
        og_img = tree.css_first('meta[property="og:image"]')
        if og_img:
            cover = og_img.attributes.get("content", "")
            # Upgrade /small/ to /large/
            result.cover_url = cover.replace("/small/", "/large/")

    # --- Sample audio URL ---
    sample_link = tree.css_first('a[href*="sample"]')
    if sample_link:
        href = sample_link.attributes.get("href", "")
        if href:
            result.sample_url = href if href.startswith("http") else f"https://virtualo.pl{href}"

    if not result.sample_url:
        dl_match = re.search(
            r'href="([^"]*(?:download=1|sample)[^"]*)"',
            full_text,
            re.IGNORECASE,
        )
        if dl_match:
            href = dl_match.group(1)
            result.sample_url = href if href.startswith("http") else f"https://virtualo.pl{href}"

    # --- Reviews ---
    review_nodes = tree.css('[class*="review"], [class*="opinia"]')
    for rn in review_nodes:
        # Skip watermark/DRM descriptions and newsletter sections
        rn_text = rn.text(strip=True) or ""
        if "Watermark" in rn_text[:50] or "newsletter" in rn_text.lower()[:50]:
            continue

        username_node = rn.css_first('[class*="author"], [class*="user"], strong')
        text_node = rn.css_first('[class*="text"], [class*="content"], p')
        rating_node_r = rn.css_first('[class*="rating"], [class*="stars"]')
        date_node = rn.css_first('[class*="date"], time')

        review_text = _text(text_node) or _text(rn)
        if review_text and len(review_text) > 10:
            # Additional filter: skip if it's about watermark/DRM
            if "Watermark" in review_text[:80] or "znakowani" in review_text[:80]:
                continue
            review = {
                "username": _text(username_node) or "Anonim",
                "text": review_text,
                "rating": None,
                "date": _text(date_node),
            }
            if rating_node_r:
                rating_val = re.search(r"(\d)", _text(rating_node_r) or "")
                if rating_val:
                    review["rating"] = int(rating_val.group(1))
            result.reviews.append(review)

    return result


# ---------------------------------------------------------------------------
# List page parser (category / search results)
# ---------------------------------------------------------------------------


def parse_list_page(html: str) -> tuple[list[str], Optional[str]]:
    """
    Parse a Virtualo listing page.

    Returns:
        tuple of (audiobook_urls, next_page_url)
    """
    tree = HTMLParser(html)
    audiobook_urls: list[str] = []

    # Links to individual audiobook pages
    links = tree.css('a[href*="/audiobook/"]')
    seen = set()
    for link in links:
        href = link.attributes.get("href", "")
        if href and "/audiobook/" in href and href not in seen:
            if not href.startswith("http"):
                href = f"https://virtualo.pl{href}"
            # Filter out fragment links
            if "#" not in href:
                audiobook_urls.append(href)
                seen.add(href)

    # Next page
    next_page: Optional[str] = None
    next_link = tree.css_first('a[rel="next"], a.next, [class*="next"] a')
    if next_link:
        href = next_link.attributes.get("href", "")
        if href:
            next_page = href if href.startswith("http") else f"https://virtualo.pl{href}"

    return audiobook_urls, next_page
