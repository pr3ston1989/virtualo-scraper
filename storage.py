"""Persistence layer – saving parsed data to the database."""

import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from models import (
    Author,
    Book,
    Category,
    Collection,
    Narrator,
    Publisher,
    Review,
    ScrapeQueue,
    Translator,
)
from parsers import ParsedAudiobook

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helper: get-or-create pattern
# ---------------------------------------------------------------------------


def _get_or_create(session: Session, model, **kwargs):
    """Return existing instance or create a new one."""
    instance = session.execute(select(model).filter_by(**kwargs)).scalar_one_or_none()
    if instance is None:
        instance = model(**kwargs)
        session.add(instance)
        session.flush()
    return instance


# ---------------------------------------------------------------------------
# Save audiobook
# ---------------------------------------------------------------------------


def save_audiobook(session: Session, data: ParsedAudiobook) -> Book:
    """Persist parsed audiobook data. Updates if URL already exists."""
    existing = session.execute(
        select(Book).where(Book.url == data.url)
    ).scalar_one_or_none()

    if existing:
        book = existing
        logger.debug(f"Updating existing book: {data.title}")
    else:
        book = Book(url=data.url)
        session.add(book)
        logger.info(f"Adding new book: {data.title}")

    # Scalar fields
    book.title = data.title
    book.description = data.description
    book.avg_rating = data.avg_rating
    book.rating_count = data.rating_count
    book.length_str = data.length_str
    book.duration_minutes = data.duration_minutes
    book.language = data.language
    book.type = data.type
    book.format = data.format
    book.original_title = data.original_title
    book.release_date = data.release_date
    book.isbn = data.isbn
    book.price = data.price
    book.price_original = data.price_original
    book.cover_url = data.cover_url
    book.sample_url = data.sample_url
    book.breadcrumb = data.breadcrumb
    book.series = data.series

    # Publisher
    if data.publisher:
        pub = _get_or_create(session, Publisher, name=data.publisher)
        book.publisher = pub

    # Category
    if data.category:
        cat = _get_or_create(session, Category, name=data.category)
        book.category = cat

    # Authors
    book.authors = [_get_or_create(session, Author, name=n) for n in data.authors]

    # Narrators
    book.narrators = [_get_or_create(session, Narrator, name=n) for n in data.narrators]

    # Translators
    book.translators = [_get_or_create(session, Translator, name=n) for n in data.translators]

    # Reviews — only add new ones (avoid duplicates on re-scrape)
    if data.reviews:
        existing_texts = set()
        if existing:
            existing_texts = {r.text[:100] for r in book.reviews}

        for rev_data in data.reviews:
            if rev_data["text"][:100] not in existing_texts:
                review = Review(
                    book=book,
                    username=rev_data["username"],
                    rating=rev_data.get("rating"),
                    date=rev_data.get("date"),
                    text=rev_data["text"],
                )
                session.add(review)

    session.flush()
    return book


# ---------------------------------------------------------------------------
# Queue management
# ---------------------------------------------------------------------------


def enqueue_url(session: Session, url: str, url_type: str, priority: int = 0) -> bool:
    """
    Add URL to scrape queue if not already present.
    Returns True if URL was newly added, False if already existed.
    """
    exists = session.execute(
        select(ScrapeQueue.id).where(ScrapeQueue.url == url)
    ).scalar_one_or_none()
    if not exists:
        item = ScrapeQueue(url=url, type=url_type, status="pending", priority=priority)
        session.add(item)
        return True
    return False


def enqueue_urls_batch(session: Session, urls: list[str], url_type: str, priority: int = 0) -> int:
    """
    Batch-enqueue multiple URLs. More efficient than individual calls.
    Returns number of newly added URLs.
    """
    if not urls:
        return 0

    # Get existing URLs in one query
    existing = set(
        session.execute(
            select(ScrapeQueue.url).where(ScrapeQueue.url.in_(urls))
        ).scalars().all()
    )

    new_count = 0
    for url in urls:
        if url not in existing:
            session.add(ScrapeQueue(url=url, type=url_type, status="pending", priority=priority))
            new_count += 1

    return new_count


def get_pending_urls(session: Session, url_type: str, limit: int = 50) -> list[ScrapeQueue]:
    """Get batch of pending URLs from queue."""
    stmt = (
        select(ScrapeQueue)
        .where(ScrapeQueue.type == url_type, ScrapeQueue.status == "pending")
        .order_by(ScrapeQueue.priority.desc(), ScrapeQueue.id)
        .limit(limit)
    )
    return list(session.execute(stmt).scalars().all())


def mark_done(session: Session, item: ScrapeQueue) -> None:
    """Mark queue item as completed."""
    item.status = "done"
    session.flush()


def mark_failed(session: Session, item: ScrapeQueue, error: str) -> None:
    """Mark queue item as failed with retry logic."""
    item.retry_count += 1
    item.error_message = error

    # Permanent failures: don't retry 404s or parse errors
    permanent = any(x in error for x in ("404", "Not Found", "No title parsed"))
    if permanent or item.retry_count >= 5:
        item.status = "failed"
    else:
        item.status = "pending"  # Will be retried
    session.flush()


def reset_failed(session: Session, url_type: Optional[str] = None, max_retries: int = 5) -> int:
    """
    Reset 'failed' items back to 'pending' for retry.
    Only resets items that haven't exceeded max_retries.

    Returns number of items reset.
    """
    stmt = (
        update(ScrapeQueue)
        .where(
            ScrapeQueue.status == "failed",
            ScrapeQueue.retry_count < max_retries,
        )
        .values(status="pending")
    )
    if url_type:
        stmt = stmt.where(ScrapeQueue.type == url_type)

    result = session.execute(stmt)
    session.commit()
    count = result.rowcount  # type: ignore
    if count:
        logger.info(f"Reset {count} failed items back to pending")
    return count


def get_queue_stats(session: Session) -> dict:
    """Get queue statistics by type and status."""
    stats = {}
    rows = session.execute(
        select(
            ScrapeQueue.type,
            ScrapeQueue.status,
            func.count(ScrapeQueue.id),
        ).group_by(ScrapeQueue.type, ScrapeQueue.status)
    ).all()
    for url_type, status, count in rows:
        if url_type not in stats:
            stats[url_type] = {}
        stats[url_type][status] = count
    return stats
