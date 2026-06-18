"""SQLAlchemy engine/session plumbing and the declarative Base.

The database URL is read from the environment (FORGE_DATABASE_URL) — never
hard-coded, never carrying secrets in source.
"""

from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DEFAULT_DATABASE_URL_ENV = "FORGE_DATABASE_URL"


class Base(DeclarativeBase):
    """Declarative base for all FORGE L2 models."""


def get_database_url(url: str | None = None) -> str:
    """Resolve the database URL from an explicit arg or the environment."""
    resolved = url or os.environ.get(DEFAULT_DATABASE_URL_ENV)
    if not resolved:
        raise RuntimeError(
            f"database URL not set: pass url= or set {DEFAULT_DATABASE_URL_ENV}"
        )
    return resolved


def create_db_engine(url: str | None = None, *, echo: bool = False) -> Engine:
    """Create a SQLAlchemy Engine for the resolved database URL.

    The client speaks UTF-8 explicitly so non-ASCII content (e.g. ``€`` in
    funding evidence) round-trips regardless of the server's default encoding.
    """
    return create_engine(
        get_database_url(url), echo=echo, future=True, client_encoding="utf8"
    )


def make_session_factory(engine: Engine) -> sessionmaker:
    """Build a sessionmaker bound to ``engine``."""
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)
