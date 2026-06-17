from __future__ import annotations

import pytest

from app.cli import create_user
from app.models.user import User


class _Cfg:
    class security:
        allow_registration = False


def test_register_blocked_when_disabled(client, monkeypatch):
    from app.api import auth as auth_module

    monkeypatch.setattr(auth_module, "get_config", lambda: _Cfg())
    response = client.post(
        "/api/auth/register",
        json={"email": "blocked@test.com", "password": "secret123"},
    )
    assert response.status_code == 403


def test_create_user_cli_creates_account(session):
    user = create_user("admin@test.com", "secret123", session=session)
    assert user.id is not None
    assert user.email == "admin@test.com"
    # Stored password must be hashed, never plaintext.
    assert user.hashed_password != "secret123"


def test_create_user_cli_rejects_duplicate(session):
    create_user("dup@test.com", "secret123", session=session)
    with pytest.raises(ValueError):
        create_user("dup@test.com", "secret123", session=session)
    # Only one row exists.
    from sqlmodel import select

    rows = session.exec(select(User).where(User.email == "dup@test.com")).all()
    assert len(rows) == 1
