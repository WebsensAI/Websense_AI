"""
app/utils/db.py
SQLAlchemy engine + session management for the MySQL-backed data layer.

- Connection pooling is configured on the engine (pool_size / max_overflow /
  pool_timeout / pool_recycle) and `pool_pre_ping=True` so a dropped/stale
  connection is detected and transparently replaced instead of surfacing
  a "MySQL server has gone away" error to a request.
- `init_db()` creates any missing tables on startup (auto table creation).
- `session_scope()` is a context manager every caller should use: it
  commits on success and rolls back the transaction on any error, so a
  failed write never leaves a half-committed row behind.
"""
import logging
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.orm import scoped_session, sessionmaker

from app.config import Config

logger = logging.getLogger(__name__)


class DatabaseUnavailableError(Exception):
    """Raised when MySQL can't be reached (server down, wrong host/port,
    bad credentials, network blip, etc.). Callers turn this into a
    friendly, non-crashing response instead of a raw 500."""


engine = create_engine(
    Config.SQLALCHEMY_DATABASE_URI,
    pool_size=Config.DB_POOL_SIZE,
    max_overflow=Config.DB_MAX_OVERFLOW,
    pool_timeout=Config.DB_POOL_TIMEOUT,
    pool_recycle=Config.DB_POOL_RECYCLE,
    pool_pre_ping=True,
    future=True,
)

SessionLocal = scoped_session(
    sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
)


def init_db():
    """Create any tables that don't exist yet. Safe to call on every
    app startup -- it's a no-op if the tables are already there."""
    from app.models.user import Base

    try:
        Base.metadata.create_all(bind=engine)
        logger.info("Database tables verified/created successfully.")
    except OperationalError as e:
        logger.error("Could not connect to MySQL to create tables: %s", e)
        raise DatabaseUnavailableError(
            "Could not connect to the MySQL database. Check DB_HOST, DB_PORT, DB_USER, "
            "DB_PASSWORD, and DB_NAME (or DATABASE_URL), and make sure the MySQL server is running."
        ) from e


@contextmanager
def session_scope():
    """Transactional scope around a block of ORM work.

    Usage:
        with session_scope() as session:
            session.add(obj)
            # commits automatically at the end of the `with` block

    Commits on a clean exit, rolls back on any exception, always returns
    the connection to the pool, and converts a lost/unavailable database
    connection into a `DatabaseUnavailableError` so callers can show a
    friendly message instead of crashing.
    """
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except (OperationalError, DBAPIError) as e:
        session.rollback()
        logger.error("Database connection error: %s", e)
        raise DatabaseUnavailableError(
            "Lost connection to the database. Please try again in a moment."
        ) from e
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
        SessionLocal.remove()
