import logging
import os
from collections.abc import Generator
from typing import Any

from sqlmodel import Session, SQLModel, create_engine

from .config import get_config

logger = logging.getLogger(__name__)


def _database_url() -> str:
    """Resolve the DB URL, letting the DATABASE_URL env var win (for Docker/prod)."""
    return os.getenv("DATABASE_URL") or get_config().database.url


def _is_sqlite(url: str) -> bool:
    return url.startswith("sqlite")


def _engine_options(url: str) -> dict[str, Any]:
    if _is_sqlite(url):
        # SQLite + a threadpool/uvicorn needs check_same_thread disabled.
        return {"echo": False, "connect_args": {"check_same_thread": False}}
    # Server databases (Postgres): recycle dead connections instead of erroring.
    return {"echo": False, "pool_pre_ping": True}


def make_engine(url: str):
    return create_engine(url, **_engine_options(url))


engine = make_engine(_database_url())


def init_db():
    # Import models to register them with SQLModel metadata
    from ..models import (
        agent,  # noqa: F401
        knowledge,  # noqa: F401
        task,  # noqa: F401
        user,  # noqa: F401
    )

    # Ensure the database directory exists for SQLite
    url = _database_url()
    if _is_sqlite(url):
        import re

        # Extract file path from sqlite:///path
        match = re.search(r"sqlite:///(.+)", url)
        if match:
            from pathlib import Path

            db_path = Path(match.group(1))
            db_path.parent.mkdir(parents=True, exist_ok=True)

    SQLModel.metadata.create_all(engine)
    _migrate_db()


def _migrate_db() -> None:
    """Add missing columns to existing SQLite tables for backward compatibility.

    This uses SQLite-only PRAGMA/ALTER. On server databases (Postgres) the schema
    is created complete by create_all(), so this lightweight shim is skipped.
    """
    if not _is_sqlite(_database_url()):
        return
    migrations = [
        ("task", "highlight", "BOOLEAN DEFAULT 0"),
        ("task", "highlight_stats", "TEXT"),
        ("task", "highlight_status", "TEXT"),
        ("task", "highlight_sentences", "TEXT"),
        ("task", "result_dual_pdf_path", "TEXT"),
        ("task", "summary_json", "TEXT"),
    ]
    with engine.connect() as conn:
        for table, column, col_type in migrations:
            try:
                existing = [row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})")]
                if column not in existing:
                    conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
                    conn.commit()
                    logger.info("Migrated: added %s.%s", table, column)
            except Exception as exc:
                logger.debug("Migration skip %s.%s: %s", table, column, exc)


def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session
