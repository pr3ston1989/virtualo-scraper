"""Quick stats utility to check scraper progress."""

from sqlalchemy import func, select

from db import get_session, init_db
from models import Author, Book, Category, Narrator, Publisher, Review, ScrapeQueue


def show_stats() -> None:
    """Print database statistics."""
    init_db()
    session = get_session()

    try:
        books = session.execute(select(func.count(Book.id))).scalar() or 0
        authors = session.execute(select(func.count(Author.id))).scalar() or 0
        narrators = session.execute(select(func.count(Narrator.id))).scalar() or 0
        publishers = session.execute(select(func.count(Publisher.id))).scalar() or 0
        categories = session.execute(select(func.count(Category.id))).scalar() or 0
        reviews = session.execute(select(func.count(Review.id))).scalar() or 0

        # Queue stats
        queue_pending = session.execute(
            select(func.count(ScrapeQueue.id)).where(ScrapeQueue.status == "pending")
        ).scalar() or 0
        queue_done = session.execute(
            select(func.count(ScrapeQueue.id)).where(ScrapeQueue.status == "done")
        ).scalar() or 0
        queue_failed = session.execute(
            select(func.count(ScrapeQueue.id)).where(ScrapeQueue.status == "failed")
        ).scalar() or 0

        print("=" * 50)
        print("  Virtualo.pl Scraper - Database Stats")
        print("=" * 50)
        print(f"  Books:       {books:>8}")
        print(f"  Authors:     {authors:>8}")
        print(f"  Narrators:   {narrators:>8}")
        print(f"  Publishers:  {publishers:>8}")
        print(f"  Categories:  {categories:>8}")
        print(f"  Reviews:     {reviews:>8}")
        print("-" * 50)
        print(f"  Queue pending:  {queue_pending:>6}")
        print(f"  Queue done:     {queue_done:>6}")
        print(f"  Queue failed:   {queue_failed:>6}")
        print("=" * 50)

    finally:
        session.close()


if __name__ == "__main__":
    show_stats()
