from __future__ import annotations

from types import SimpleNamespace

import fitz
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.api.deps import get_current_user
from app.api.reading_routes import create_reading_router
from app.core.config import LLMConfig
from app.models.task import Task, TaskStatus
from app.models.user import User
from app.services.reading_service import ReadingService


def _pdf() -> bytes:
    document = fitz.open()
    page = document.new_page()
    page.insert_text((50, 80), "1 Introduction", fontsize=16)
    page.insert_text((50, 110), "This is the opening sentence. This is the second sentence.")
    data = document.tobytes()
    document.close()
    return data


def _client(tmp_path):
    from app.models import knowledge as _knowledge  # noqa: F401
    from app.models import reading as _reading  # noqa: F401
    from app.models import user as _user  # noqa: F401

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    source = tmp_path / "paper.pdf"
    source.write_bytes(_pdf())
    task = Task(
        task_id="task-1", filename="paper.pdf", user_id=1, status=TaskStatus.COMPLETED, original_pdf_path=str(source)
    )
    with Session(engine) as session:
        session.add(User(id=1, email="reader@example.com", hashed_password="hash"))
        session.add(task)
        session.commit()
    config = SimpleNamespace(processing=SimpleNamespace(max_concurrent=1), llm=LLMConfig())
    service = ReadingService(config, engine)
    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: User(id=1, email="reader@example.com", hashed_password="hash")
    app.include_router(create_reading_router(service))
    return TestClient(app), engine


def test_workspace_and_state_are_persistent(tmp_path):
    client, engine = _client(tmp_path)
    response = client.get("/api/reading/task-1")
    assert response.status_code == 200
    block = response.json()["document"]["blocks"][1]["id"]
    saved = client.patch(
        "/api/reading/task-1/state", json={"block_id": block, "mode": "bilingual", "understood": [block]}
    )
    assert saved.status_code == 200
    assert saved.json()["mode"] == "bilingual"
    with Session(engine) as session:
        assert session.get(Task, "task-1") is not None


def test_state_rejects_unknown_block(tmp_path):
    client, _ = _client(tmp_path)
    response = client.patch("/api/reading/task-1/state", json={"block_id": "invented"})
    assert response.status_code == 422
