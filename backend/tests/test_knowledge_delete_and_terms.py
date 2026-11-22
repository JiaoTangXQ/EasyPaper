"""Deleting notes must not break on saved terms, and term dates must be unambiguous UTC."""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.api import knowledge_routes as knowledge_routes_module
from app.api import term_routes as term_routes_module
from app.api.deps import get_current_user
from app.api.knowledge_routes import create_knowledge_router
from app.api.term_routes import create_term_router
from app.models import knowledge as knowledge_model  # noqa: F401
from app.models import task as task_model  # noqa: F401
from app.models import user as user_model  # noqa: F401
from app.models.knowledge import PaperKnowledge, PersonalTerm
from app.models.user import User


def _client(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    # Enforce foreign keys like the production PostgreSQL database does.
    @event.listens_for(engine, "connect")
    def _foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(knowledge_routes_module, "engine", engine)
    monkeypatch.setattr(term_routes_module, "engine", engine)
    with Session(engine) as session:
        session.add(User(id=1, email="reader@example.com", hashed_password="hash"))
        session.commit()
        session.add(PaperKnowledge(id="pk-1", user_id=1, title="Paper", extraction_status="completed"))
        session.commit()
    user = User(id=1, email="reader@example.com", hashed_password="hash")
    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: user
    app.include_router(create_knowledge_router(SimpleNamespace(model="test-model")))
    app.include_router(create_term_router())
    return TestClient(app), engine


def test_deleting_notes_keeps_saved_terms_and_unlinks_them(monkeypatch):
    client, engine = _client(monkeypatch)
    saved = client.post("/api/terms", json={"term": "throughput", "meaning": "吞吐量", "paper_id": "pk-1"})
    assert saved.status_code == 200

    response = client.delete("/api/knowledge/papers/pk-1")

    assert response.status_code == 200
    with Session(engine) as session:
        assert session.get(PaperKnowledge, "pk-1") is None
        term = session.get(PersonalTerm, saved.json()["id"])
        assert term is not None
        assert term.paper_id is None


def test_term_dates_are_serialised_as_utc(monkeypatch):
    client, engine = _client(monkeypatch)
    saved = client.post("/api/terms", json={"term": "latency", "meaning": "延迟"}).json()
    assert saved["next_review"].endswith("Z")
    assert saved["last_review"] is None

    reviewed = client.post(f"/api/terms/{saved['id']}/review", json={"quality": 5}).json()
    assert reviewed["last_review"].endswith("Z")
    due = datetime.fromisoformat(reviewed["next_review"].removesuffix("Z"))
    assert due - datetime.utcnow() > timedelta(hours=20)


def test_term_search_treats_wildcards_literally(monkeypatch):
    client, _ = _client(monkeypatch)
    client.post("/api/terms", json={"term": "100% recall", "meaning": "完全召回"})
    client.post("/api/terms", json={"term": "precision", "meaning": "精确率"})

    assert [term["term"] for term in client.get("/api/terms", params={"q": "%"}).json()] == ["100% recall"]
    assert client.get("/api/terms", params={"q": "_"}).json() == []
