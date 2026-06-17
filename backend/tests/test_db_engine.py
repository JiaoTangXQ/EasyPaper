from __future__ import annotations

from app.core.db import _database_url, _engine_options, _is_sqlite


def test_is_sqlite_detection() -> None:
    assert _is_sqlite("sqlite:///./data/app.db") is True
    assert _is_sqlite("postgresql://u:p@db:5432/easypaper") is False


def test_engine_options_sqlite() -> None:
    opts = _engine_options("sqlite:///./data/app.db")
    assert opts["connect_args"] == {"check_same_thread": False}
    assert "pool_pre_ping" not in opts


def test_engine_options_postgres() -> None:
    opts = _engine_options("postgresql://u:p@db:5432/easypaper")
    assert "connect_args" not in opts
    assert opts.get("pool_pre_ping") is True


def test_database_url_prefers_env(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@db:5432/easypaper")
    assert _database_url() == "postgresql://u:p@db:5432/easypaper"
