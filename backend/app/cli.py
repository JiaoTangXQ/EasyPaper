"""Offline account administration. Passwords are read with getpass, never argv."""

from __future__ import annotations

import argparse
import getpass
import os
import sys

from email_validator import validate_email
from sqlmodel import Session, select

from .core.config import get_config
from .core.security import get_password_hash
from .models.user import User, validate_password


def create_user(email: str, password: str, *, session: Session) -> User:
    email = validate_email(email.strip(), check_deliverability=False).normalized.lower()
    validate_password(password)
    if session.exec(select(User).where(User.email == email)).first():
        raise ValueError(f"A user with email {email!r} already exists")
    if len(session.exec(select(User)).all()) >= get_config().security.max_users:
        raise ValueError("账号数量达到上限，请先调整 security.max_users")
    user = User(email=email, hashed_password=get_password_hash(password), is_active=True)
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def change_user(email, action, *, session, password=None):
    user = session.exec(select(User).where(User.email == email.strip().lower())).first()
    if not user:
        raise ValueError("账号不存在")
    if action == "reset-password":
        user.hashed_password = get_password_hash(validate_password(password))
    else:
        user.is_active = action == "enable-user"
    user.token_version += 1
    session.add(user)
    session.commit()


def read_password():
    password = getpass.getpass("新密码（至少 12 个字符）: ")
    if password != getpass.getpass("再次输入: "):
        raise ValueError("两次密码不一致")
    return validate_password(password)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.cli", description="EasyPaper admin tools")
    sub = parser.add_subparsers(dest="command", required=True)
    for action in ("create-user", "reset-password", "disable-user", "enable-user"):
        sub.add_parser(action).add_argument("email")
    sub.add_parser("list-users")
    worker = sub.add_parser("gloss-worker", help="Run a trusted local gloss preparation worker")
    worker.add_argument("--base-url", default=os.getenv("EASYPAPER_SERVER_URL", "http://127.0.0.1:8000"))
    worker.add_argument("--token", default=os.getenv("GLOSS_WORKER_TOKEN", ""))
    worker.add_argument("--label", default=os.getenv("EASYPAPER_GLOSS_WORKER_LABEL", "local-worker"))
    worker.add_argument("--poll-seconds", type=float, default=float(os.getenv("EASYPAPER_GLOSS_WORKER_POLL_SECONDS", "5")))
    know = sub.add_parser("knowledge-worker", help="Run a trusted local knowledge extraction worker")
    know.add_argument("--base-url", default=os.getenv("EASYPAPER_SERVER_URL", "http://127.0.0.1:8000"))
    know.add_argument("--token", default=os.getenv("KNOWLEDGE_WORKER_TOKEN", ""))
    know.add_argument("--label", default=os.getenv("EASYPAPER_KNOWLEDGE_WORKER_LABEL", "local-knowledge-worker"))
    know.add_argument("--poll-seconds", type=float, default=float(os.getenv("EASYPAPER_KNOWLEDGE_WORKER_POLL_SECONDS", "5")))
    local = sub.add_parser("local-worker", help="Run gloss and knowledge workers together (Mac)")
    local.add_argument("--base-url", default=os.getenv("EASYPAPER_SERVER_URL", "http://127.0.0.1:8000"))
    local.add_argument("--gloss-token", default=os.getenv("GLOSS_WORKER_TOKEN", ""))
    local.add_argument(
        "--knowledge-token",
        default=os.getenv("KNOWLEDGE_WORKER_TOKEN", "") or os.getenv("GLOSS_WORKER_TOKEN", ""),
    )
    local.add_argument("--gloss-label", default=os.getenv("EASYPAPER_GLOSS_WORKER_LABEL", "local-worker"))
    local.add_argument(
        "--knowledge-label",
        default=os.getenv("EASYPAPER_KNOWLEDGE_WORKER_LABEL", "local-knowledge-worker"),
    )
    local.add_argument("--poll-seconds", type=float, default=float(os.getenv("EASYPAPER_GLOSS_WORKER_POLL_SECONDS", "5")))
    local.add_argument(
        "--knowledge",
        dest="knowledge_enabled",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Poll knowledge-worker jobs (default on; disable for gloss-only)",
    )
    args = parser.parse_args(argv)
    from .core.db import engine, init_db

    init_db()
    if args.command == "gloss-worker":
        from .gloss_worker.runner import run_worker

        try:
            return run_worker(
                base_url=args.base_url,
                token=args.token,
                worker_label=args.label,
                poll_seconds=args.poll_seconds,
            )
        except (ValueError, KeyboardInterrupt) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
    if args.command == "knowledge-worker":
        from .knowledge_worker.runner import run_worker as run_knowledge_worker

        try:
            return run_knowledge_worker(
                base_url=args.base_url,
                token=args.token,
                worker_label=args.label,
                poll_seconds=args.poll_seconds,
            )
        except (ValueError, KeyboardInterrupt) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
    if args.command == "local-worker":
        from .local_worker.runner import run_local_worker

        try:
            return run_local_worker(
                base_url=args.base_url,
                gloss_token=args.gloss_token,
                knowledge_token=args.knowledge_token,
                gloss_label=args.gloss_label,
                knowledge_label=args.knowledge_label,
                poll_seconds=args.poll_seconds,
                knowledge_enabled=args.knowledge_enabled,
            )
        except (ValueError, KeyboardInterrupt) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
    try:
        with Session(engine) as session:
            if args.command == "list-users":
                for user in session.exec(select(User)).all():
                    print(f"{user.id}\t{user.email}\t{'active' if user.is_active else 'disabled'}")
            elif args.command == "create-user":
                user = create_user(args.email, read_password(), session=session)
                print(f"created user id={user.id} email={user.email}")
            else:
                password = read_password() if args.command == "reset-password" else None
                change_user(args.email, args.command, session=session, password=password)
                print("账号已更新，旧登录已失效")
    except (ValueError, EOFError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
