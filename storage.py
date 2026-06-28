"""Persistence layer – saving parsed data to the database."""

import logging
from typing import Optional

from sqlalchemy import select
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
    # Check if book already in DB
    existing = session.execute(
        select(Book).where(Book.url == data.url)
    ).scalar_one_or_none()

    if existing:
        book = existing
        logger.info(f"Updating existing book: {data.title}")
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

    # Reviews
    if data.reviews and not existing:
        for rev_data in data.reviews:
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


def enqueue_url(session: Session, url: str, url_type: str, priority: int = 0) -> None:
    """Add URL to scrape queue if not already present."""
    exists = session.execute(
        select(ScrapeQueue).where(ScrapeQueue.url == url)
    ).scalar_one_or_none()
    if not exists:
        item = ScrapeQueue(url=url, type=url_type, status="pending", priority=priority)
        session.add(item)


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
    """Mark queue item as failed."""
    item.retry_count += 1
    item.error_message = error
    if item.retry_count >= 3:
        item.status = "failed"
    else:
        item.status = "pending"  # Will be retried
    session.flush()
