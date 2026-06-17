"""Administrative command-line tools.

Usage:
    python -m app.cli create-user <email> <password>

Used to provision accounts when self-service registration is disabled
(security.allow_registration: false).
"""

from __future__ import annotations

import argparse
import sys

from sqlmodel import Session, select

from .core.security import get_password_hash
from .models.user import User


def create_user(email: str, password: str, *, session: Session) -> User:
    """Create an active user. Raises ValueError if the email already exists."""
    email = email.strip().lower()
    if not email or not password:
        raise ValueError("email and password are required")

    existing = session.exec(select(User).where(User.email == email)).first()
    if existing:
        raise ValueError(f"A user with email {email!r} already exists")

    user = User(email=email, hashed_password=get_password_hash(password), is_active=True)
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def _cmd_create_user(args: argparse.Namespace) -> int:
    # Imported lazily so importing this module for tests doesn't touch the DB engine.
    from .core.db import engine, init_db

    init_db()
    with Session(engine) as session:
        try:
            user = create_user(args.email, args.password, session=session)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
    print(f"created user id={user.id} email={user.email}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.cli", description="EasyPaper admin tools")
    sub = parser.add_subparsers(dest="command", required=True)

    p_create = sub.add_parser("create-user", help="Create a new user account")
    p_create.add_argument("email")
    p_create.add_argument("password")
    p_create.set_defaults(func=_cmd_create_user)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
