from __future__ import annotations

import json
from pathlib import Path
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
from app.models.knowledge import PaperKnowledge
from app.models.user import User


def _build_client(monkeypatch) -> tuple[TestClient, object]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(knowledge_routes_module, "engine", engine)

    with Session(engine) as session:
        session.add(User(id=1, email="user@example.com", hashed_password="hash"))
        session.add(
            PaperKnowledge(
                id="paper-1",
                task_id="task-1",
                user_id=1,
                title="Test/Paper",
                extraction_status="completed",
                knowledge_json=json.dumps(
                    {
                        "id": "paper-1",
                        "metadata": {"title": "Test/Paper", "authors": [{"name": "Alice"}]},
                        "summary": "A short summary.",
                        "entities": [{"name": "BERT/Model", "type": "model", "definition": "A model."}],
                    }
                ),
            )
        )
        session.commit()

    auth_user = User(id=1, email="user@example.com", hashed_password="hash")
    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: auth_user
    app.include_router(create_knowledge_router(SimpleNamespace(model="test-model")))
    return TestClient(app), engine


def test_save_obsidian_settings_and_sync_paper(monkeypatch, tmp_path: Path) -> None:
    client, _engine = _build_client(monkeypatch)

    settings = client.post(
        "/api/knowledge/settings/obsidian",
        json={"vault_path": str(tmp_path), "root_folder": "EasyPaper"},
    )
    assert settings.status_code == 200
    assert settings.json()["vault_path"] == str(tmp_path)

    response = client.post("/api/knowledge/papers/paper-1/sync/obsidian")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "synced"
    assert body["paper_note"] == "EasyPaper/Papers/Test_Paper.md"
    assert (tmp_path / "EasyPaper" / "Papers" / "Test_Paper.md").exists()
    assert (tmp_path / "EasyPaper" / "Entities" / "BERT_Model.md").exists()
