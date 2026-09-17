"""Engine and connection management.

SQLite needs two pragmas to behave the way the executor assumes:

* ``foreign_keys=ON``  -- referential integrity is off by default in SQLite.
* ``journal_mode=WAL`` -- readers do not block the writer, which keeps the UI
  responsive while an agent run holds a write transaction.

Both are applied per connection and are skipped for non-SQLite dialects, so a
Postgres/Supabase ``DATABASE_URL`` works without touching this file.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Connection, Engine

from app.config import get_settings
from app.db.schema import metadata

_engine: Engine | None = None


def _configure_sqlite(engine: Engine) -> None:
    @event.listens_for(engine, "connect")
    def _set_pragmas(dbapi_conn, _record):  # pragma: no cover - driver callback
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA journal_mode=WAL")
        cur.close()


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        url = get_settings().database_url
        is_sqlite = url.startswith("sqlite")
        _engine = create_engine(
            url,
            future=True,
            # check_same_thread=False: FastAPI serves requests from a threadpool.
            connect_args={"check_same_thread": False} if is_sqlite else {},
        )
        if is_sqlite:
            _configure_sqlite(_engine)
    return _engine


@contextmanager
def transaction() -> Iterator[Connection]:
    """A single atomic unit of work.

    The executor relies on this: the purchase order row, the budget commitment and
    the capacity reservation either all land or none do. A partial write that
    creates an order without its matching commitment is exactly the inconsistency
    this prevents.
    """
    engine = get_engine()
    with engine.begin() as conn:
        yield conn


@contextmanager
def connection() -> Iterator[Connection]:
    """Read-only access; no implicit transaction semantics intended."""
    engine = get_engine()
    with engine.connect() as conn:
        yield conn


def create_all() -> None:
    metadata.create_all(get_engine())


def drop_all() -> None:
    metadata.drop_all(get_engine())


def reset_database() -> None:
    """Drop and recreate every table. Used by the demo reset endpoint and tests."""
    drop_all()
    create_all()


def sqlite_path() -> Path | None:
    url = get_settings().database_url
    if not url.startswith("sqlite"):
        return None
    return Path(url.split("///")[-1]).resolve()
