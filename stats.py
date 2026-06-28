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

        # Queue stats by type and status
        queue_rows = session.execute(
            select(
                ScrapeQueue.type,
                ScrapeQueue.status,
                func.count(ScrapeQueue.id),
            ).group_by(ScrapeQueue.type, ScrapeQueue.status)
        ).all()

        # Books with/without covers
        books_with_cover = session.execute(
            select(func.count(Book.id)).where(Book.cover_local_path.isnot(None))
        ).scalar() or 0

        # Books with ratings
        books_with_rating = session.execute(
            select(func.count(Book.id)).where(Book.avg_rating.isnot(None))
        ).scalar() or 0

        # Average rating
        avg_rating = session.execute(
            select(func.avg(Book.avg_rating)).where(Book.avg_rating.isnot(None))
        ).scalar()

        print("=" * 55)
        print("  Virtualo.pl Audiobook Scraper — Database Stats")
        print("=" * 55)
        print(f"  Books:            {books:>8}")
        print(f"  Authors:          {authors:>8}")
        print(f"  Narrators:        {narrators:>8}")
        print(f"  Publishers:       {publishers:>8}")
        print(f"  Categories:       {categories:>8}")
        print(f"  Reviews:          {reviews:>8}")
        print("-" * 55)
        print(f"  With covers:      {books_with_cover:>8}")
        print(f"  With ratings:     {books_with_rating:>8}")
        if avg_rating:
            print(f"  Avg rating:         {avg_rating:.2f}")
        print("-" * 55)
        print("  Queue:")

        queue_data: dict = {}
        for url_type, status, count in queue_rows:
            if url_type not in queue_data:
                queue_data[url_type] = {}
            queue_data[url_type][status] = count

        for url_type in sorted(queue_data.keys()):
            statuses = queue_data[url_type]
            total = sum(statuses.values())
            parts = [f"{s}={c}" for s, c in sorted(statuses.items())]
            print(f"    {url_type:>10}: {total:>6} total ({', '.join(parts)})")

        print("=" * 55)

        # Show failed items (if any)
        failed_count = session.execute(
            select(func.count(ScrapeQueue.id)).where(ScrapeQueue.status == "failed")
        ).scalar() or 0

        if failed_count > 0:
            print(f"\n  ⚠ {failed_count} failed items. Run with --retry-only to retry.")
            # Show sample errors
            failed_items = session.execute(
                select(ScrapeQueue.url, ScrapeQueue.error_message, ScrapeQueue.retry_count)
                .where(ScrapeQueue.status == "failed")
                .limit(5)
            ).all()
            for url, err, retries in failed_items:
                short_url = url[-60:] if len(url) > 60 else url
                short_err = (err or "")[:50]
                print(f"    ...{short_url} ({retries}x): {short_err}")
            if failed_count > 5:
                print(f"    ... and {failed_count - 5} more")

    finally:
        session.close()


if __name__ == "__main__":
    show_stats()
