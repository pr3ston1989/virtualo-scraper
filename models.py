"""SQLAlchemy models for Virtualo audiobook scraper."""

from typing import List, Optional

from sqlalchemy import (
    Column,
    Float,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Junction tables
# ---------------------------------------------------------------------------

book_authors = Table(
    "book_authors",
    Base.metadata,
    Column("book_id", ForeignKey("books.id"), primary_key=True),
    Column("author_id", ForeignKey("authors.id"), primary_key=True),
)

book_narrators = Table(
    "book_narrators",
    Base.metadata,
    Column("book_id", ForeignKey("books.id"), primary_key=True),
    Column("narrator_id", ForeignKey("narrators.id"), primary_key=True),
)

book_collections = Table(
    "book_collections",
    Base.metadata,
    Column("book_id", ForeignKey("books.id"), primary_key=True),
    Column("collection_id", ForeignKey("collections.id"), primary_key=True),
)

book_translators = Table(
    "book_translators",
    Base.metadata,
    Column("book_id", ForeignKey("books.id"), primary_key=True),
    Column("translator_id", ForeignKey("translators.id"), primary_key=True),
)


# ---------------------------------------------------------------------------
# Entity tables
# ---------------------------------------------------------------------------


class Author(Base):
    __tablename__ = "authors"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)


class Narrator(Base):
    __tablename__ = "narrators"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)


class Translator(Base):
    __tablename__ = "translators"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)


class Collection(Base):
    __tablename__ = "collections"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)


class Publisher(Base):
    __tablename__ = "publishers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)


# ---------------------------------------------------------------------------
# Main Book table
# ---------------------------------------------------------------------------


class Book(Base):
    __tablename__ = "books"

    id: Mapped[int] = mapped_column(primary_key=True)
    url: Mapped[str] = mapped_column(String(500), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[Optional[str]] = mapped_column(Text)

    # Ratings
    avg_rating: Mapped[Optional[float]] = mapped_column(Float)
    rating_count: Mapped[Optional[int]] = mapped_column(Integer)

    # Duration / length
    length_str: Mapped[Optional[str]] = mapped_column(String(100))
    duration_minutes: Mapped[Optional[int]] = mapped_column(Integer)

    # Metadata
    language: Mapped[Optional[str]] = mapped_column(String(50))
    type: Mapped[Optional[str]] = mapped_column(String(100))  # e.g. "Audiobook"
    format: Mapped[Optional[str]] = mapped_column(String(50))  # e.g. "MP3"
    original_title: Mapped[Optional[str]] = mapped_column(String(500))
    release_date: Mapped[Optional[str]] = mapped_column(String(100))
    isbn: Mapped[Optional[str]] = mapped_column(String(50))

    # Pricing
    price: Mapped[Optional[float]] = mapped_column(Float)
    price_original: Mapped[Optional[float]] = mapped_column(Float)

    # Extra content
    why_worth_it: Mapped[Optional[str]] = mapped_column(Text)
    series: Mapped[Optional[str]] = mapped_column(String(500))

    # Cover
    cover_url: Mapped[Optional[str]] = mapped_column(String(500))
    cover_local_path: Mapped[Optional[str]] = mapped_column(String(500))

    # Sample audio
    sample_url: Mapped[Optional[str]] = mapped_column(String(500))

    # Breadcrumb path (serialized, e.g. "audiobooki > Dla dzieci > Klasyka")
    breadcrumb: Mapped[Optional[str]] = mapped_column(String(500))

    # Relationships
    publisher_id: Mapped[Optional[int]] = mapped_column(ForeignKey("publishers.id"))
    publisher: Mapped[Optional[Publisher]] = relationship()

    category_id: Mapped[Optional[int]] = mapped_column(ForeignKey("categories.id"))
    category: Mapped[Optional[Category]] = relationship()

    authors: Mapped[List[Author]] = relationship(secondary=book_authors)
    narrators: Mapped[List[Narrator]] = relationship(secondary=book_narrators)
    translators: Mapped[List[Translator]] = relationship(secondary=book_translators)
    collections: Mapped[List[Collection]] = relationship(secondary=book_collections)

    reviews: Mapped[List["Review"]] = relationship(back_populates="book")


# ---------------------------------------------------------------------------
# Reviews
# ---------------------------------------------------------------------------


class Review(Base):
    __tablename__ = "reviews"

    id: Mapped[int] = mapped_column(primary_key=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id"))
    username: Mapped[str] = mapped_column(String(255))
    rating: Mapped[Optional[int]] = mapped_column(Integer)
    date: Mapped[Optional[str]] = mapped_column(String(100))
    text: Mapped[str] = mapped_column(Text)

    book: Mapped["Book"] = relationship(back_populates="reviews")


# ---------------------------------------------------------------------------
# Scrape queue
# ---------------------------------------------------------------------------


class ScrapeQueue(Base):
    __tablename__ = "scrape_queue"

    id: Mapped[int] = mapped_column(primary_key=True)
    url: Mapped[str] = mapped_column(String(500), unique=True, index=True)
    type: Mapped[str] = mapped_column(String(50))  # "sitemap" / "list" / "book"
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    priority: Mapped[int] = mapped_column(default=0)
    retry_count: Mapped[int] = mapped_column(default=0)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[Optional[str]] = mapped_column(String(50))
    updated_at: Mapped[Optional[str]] = mapped_column(String(50))
