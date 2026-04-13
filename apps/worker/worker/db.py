"""Synchronous Postgres connection pool for Celery worker tasks.

Uses a ThreadedConnectionPool so each worker thread gets its own connection
from the pool without blocking. The pool is lazily initialised on first use
and reused across task invocations in the same worker process.
"""

from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from typing import Generator

import psycopg2
import psycopg2.extras
import psycopg2.pool

from worker.config import get_settings

logger = logging.getLogger(__name__)

_pool: psycopg2.pool.ThreadedConnectionPool | None = None
_lock = threading.Lock()


def _get_pool() -> psycopg2.pool.ThreadedConnectionPool:
    global _pool
    if _pool is None:
        with _lock:
            if _pool is None:
                settings = get_settings()
                # pydantic PostgresDsn uses postgresql+asyncpg scheme — strip the driver part
                dsn = str(settings.database_url).replace("+asyncpg", "")
                _pool = psycopg2.pool.ThreadedConnectionPool(
                    minconn=2,
                    maxconn=settings.celery_worker_concurrency + 2,
                    dsn=dsn,
                )
                logger.info("Postgres connection pool initialised minconn=2 maxconn=%d",
                            settings.celery_worker_concurrency + 2)
    return _pool


@contextmanager
def get_connection() -> Generator[psycopg2.extensions.connection, None, None]:
    """Yield a Postgres connection from the pool, returning it on exit."""
    pool = _get_pool()
    conn = pool.getconn()
    conn.autocommit = False
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


@contextmanager
def get_cursor(
    cursor_factory: type = psycopg2.extras.RealDictCursor,
) -> Generator[psycopg2.extras.RealDictCursor, None, None]:
    """Yield a cursor within a managed connection."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=cursor_factory) as cur:
            yield cur
