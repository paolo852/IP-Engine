"""Shared pytest fixtures: a migrated Postgres and an isolated session per test."""

from __future__ import annotations

import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from forge.db.base import create_db_engine, make_session_factory

from ._pg import PostgresUnavailable, start_embedded

_TABLES = (
    "asset_outcome",
    "committee_decision",
    "profile_grounding",
    "asset_profile",
    "field_provenance",
    "evidence",
    "asset",
    "source",
)


@pytest.fixture(scope="session")
def database_url() -> str:
    """Resolve a test database URL, booting an ephemeral cluster if needed."""
    url = os.environ.get("FORGE_TEST_DATABASE_URL") or os.environ.get("FORGE_DATABASE_URL")
    if url:
        yield url
        return

    try:
        pg = start_embedded()
    except PostgresUnavailable as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"no PostgreSQL available for tests: {exc}")
    try:
        yield pg.url
    finally:
        pg.stop()


@pytest.fixture(scope="session")
def engine(database_url):
    """Engine bound to a freshly-migrated schema (via Alembic, not create_all)."""
    eng = create_db_engine(database_url)

    repo_root = os.path.dirname(os.path.dirname(__file__))
    cfg = Config(os.path.join(repo_root, "alembic.ini"))
    # env.py reads the URL from the environment; point it at the test DB.
    os.environ["FORGE_DATABASE_URL"] = database_url
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")

    yield eng
    eng.dispose()


@pytest.fixture()
def session(engine):
    """A session that is truncated clean after each test (repository commits)."""
    factory = make_session_factory(engine)
    sess = factory()
    try:
        yield sess
    finally:
        sess.rollback()
        sess.execute(text("TRUNCATE " + ", ".join(_TABLES) + " RESTART IDENTITY CASCADE"))
        sess.commit()
        sess.close()
