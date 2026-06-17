from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, create_engine

from app.api.deps import get_current_user
from app.api.routes import create_router
from app.models import task as task_model  # noqa: F401
from app.models import user as user_model  # noqa: F401
from app.models.user import User
from app.services import task_manager as task_manager_module
from app.services.task_manager import TaskManager


def _build_client(monkeypatch, current_user_id: int) -> tuple[TestClient, str]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(task_manager_module, "engine", engine)

    manager = TaskManager(ttl_minutes=30)
    # Task is owned by user 1.
    task = manager.create_task("paper.pdf", user_id=1, mode="translate")

    auth_user = User(id=current_user_id, email="user@example.com", hashed_password="hash")
    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: auth_user
    app.include_router(create_router(manager, SimpleNamespace()))
    return TestClient(app), task.task_id


def test_status_rejects_non_owner(monkeypatch) -> None:
    client, task_id = _build_client(monkeypatch, current_user_id=2)
    response = client.get(f"/api/status/{task_id}")
    assert response.status_code == 403


def test_status_allows_owner(monkeypatch) -> None:
    client, task_id = _build_client(monkeypatch, current_user_id=1)
    response = client.get(f"/api/status/{task_id}")
    assert response.status_code == 200
    assert response.json()["status"] is not None
