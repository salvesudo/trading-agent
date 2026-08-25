"""
SQLAlchemy engine/session setup -- Phase 5.

Postgres is the intended production database (see requirements.txt:
psycopg2-binary, and the "PostgreSQL schema" phase title). A SQLite URL
(e.g. "sqlite:///./dev.db" or "sqlite:///:memory:") also works against
these same models for local development or tests that don't want a real
Postgres server running -- every column type used in app/db/models.py is
a generic SQLAlchemy type that maps cleanly to both dialects. Nothing
about the schema is Postgres-specific.

DATABASE_URL is read from app.core.config.settings, same as everywhere
else in this project. Nothing in this module enforces any business
rule -- see app/db/repository.py for the functions that actually
read/write domain data.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings


class Base(DeclarativeBase):
    pass


def build_engine(database_url: Optional[str] = None) -> Engine:
    url = database_url or settings.database_url
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set in .env. Phase 5 needs a real database "
            "(Postgres in production; a sqlite:/// URL works for local dev "
            "and tests)."
        )
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, connect_args=connect_args, future=True)


def build_sessionmaker(engine: Optional[Engine] = None) -> sessionmaker:
    return sessionmaker(bind=engine or build_engine(), future=True, expire_on_commit=False)


def create_all_tables(engine: Optional[Engine] = None) -> None:
    """Convenience for local dev/tests: create every table directly from
    the ORM metadata, skipping Alembic. Production should use
    `alembic upgrade head` (see migrations/) instead, so schema changes
    stay tracked and reversible."""
    Base.metadata.create_all(bind=engine or build_engine())


__all__ = ["Base", "build_engine", "build_sessionmaker", "create_all_tables"]
