from __future__ import annotations

import json
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.api import knowledge_routes as knowledge_routes_module
from app.api.deps import get_current_user
from app.api.knowledge_routes import create_knowledge_router
from app.models import knowledge as knowledge_model  # noqa: F401
from app.models import user as user_model  # noqa: F401
from app.models.knowledge import Flashcard, PaperKnowledge, UserAnnotation
from app.models.user import User


def _build_client(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(knowledge_routes_module, "engine", engine)

    paper = PaperKnowledge(
        id="paper-1",
        task_id="task-1",
        user_id=1,
        title="Test Paper",
        extraction_status="completed",
    )
    with Session(engine) as session:
        session.add(User(id=1, email="user@example.com", hashed_password="hash"))
        session.add(paper)
        session.commit()

    auth_user = User(id=1, email="user@example.com", hashed_password="hash")
    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: auth_user
    app.include_router(create_knowledge_router(SimpleNamespace(model="test-model")))
    return TestClient(app), engine


def test_create_flashcard_accepts_json_body(monkeypatch):
    client, engine = _build_client(monkeypatch)

    response = client.post(
        "/api/knowledge/flashcards",
        json={
            "paper_id": "paper-1",
            "front": "What is tested?",
            "back": "JSON request bodies.",
            "tags": ["api", "flashcard"],
            "difficulty": 4,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["front"] == "What is tested?"
    assert body["back"] == "JSON request bodies."
    assert body["tags"] == ["api", "flashcard"]
    assert body["difficulty"] == 4

    with Session(engine) as session:
        card = session.get(Flashcard, body["id"])
        assert card is not None
        assert json.loads(card.tags_json) == ["api", "flashcard"]


def test_review_flashcard_accepts_json_body(monkeypatch):
    client, engine = _build_client(monkeypatch)
    with Session(engine) as session:
        session.add(
            Flashcard(
                id="fc-1",
                paper_id="paper-1",
                user_id=1,
                front="Q",
                back="A",
            )
        )
        session.commit()

    response = client.post("/api/knowledge/flashcards/fc-1/review", json={"quality": 4})

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "fc-1"
    assert body["srs"]["repetitions"] == 1


def test_create_annotation_accepts_json_body(monkeypatch):
    client, engine = _build_client(monkeypatch)

    response = client.post(
        "/api/knowledge/papers/paper-1/annotations",
        json={"type": "note", "content": "Body note", "tags": "reading,important"},
    )

    assert response.status_code == 200
    assert response.json()["content"] == "Body note"

    with Session(engine) as session:
        annotation = session.get(UserAnnotation, response.json()["id"])
        assert annotation is not None
        assert annotation.type == "note"
        assert json.loads(annotation.tags_json) == ["reading", "important"]
