import logging
from collections.abc import Generator

from sqlmodel import Session, SQLModel, create_engine

from .config import get_config

logger = logging.getLogger(__name__)

config = get_config()

connect_args = {"check_same_thread": False} if "sqlite" in config.database.url else {}
engine = create_engine(config.database.url, echo=False, connect_args=connect_args)


def init_db():
    # Import models to register them with SQLModel metadata
    from ..models import (
        agent,  # noqa: F401
        knowledge,  # noqa: F401
        task,  # noqa: F401
        user,  # noqa: F401
    )

    # Ensure the database directory exists for SQLite
    from .config import get_config

    cfg = get_config()
    if "sqlite" in cfg.database.url:
        import re

        # Extract file path from sqlite:///path
        match = re.search(r"sqlite:///(.+)", cfg.database.url)
        if match:
            from pathlib import Path

            db_path = Path(match.group(1))
            db_path.parent.mkdir(parents=True, exist_ok=True)

    SQLModel.metadata.create_all(engine)
    _migrate_db()


def _migrate_db() -> None:
    """Add missing columns to existing tables for backward compatibility."""
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
