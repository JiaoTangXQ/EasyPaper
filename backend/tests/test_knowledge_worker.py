import json
import zipfile
from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.api.knowledge_worker_routes import create_knowledge_worker_router
from app.core.config import get_config
from app.models.knowledge import PaperKnowledge
from app.models.knowledge_worker import KnowledgeWorkerJob
from app.models.task import Task, TaskStatus
from app.models.user import User
from app.services.knowledge_extractor import KnowledgeExtractor
from app.services.knowledge_worker_service import KnowledgeWorkerService


@pytest.fixture
def worker_env(monkeypatch, engine, tmp_path):
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        """
llm:
  provider: api
  api_key: test-key
  base_url: https://example.com/v1
  model: test-model
processing:
  knowledge_preparation: remote_worker
knowledge_worker:
  token: test-knowledge-token
storage:
  temp_dir: {tmp}/tmp
""".format(tmp=tmp_path),
        encoding="utf-8",
    )
    monkeypatch.setenv("APP_CONFIG_PATH", str(cfg_path))
    monkeypatch.delenv("GLOSS_WORKER_TOKEN", raising=False)
    monkeypatch.delenv("KNOWLEDGE_WORKER_TOKEN", raising=False)
    monkeypatch.delenv("EASYPAPER_KNOWLEDGE_PREPARATION", raising=False)
    get_config.cache_clear()
    cfg = get_config()
    extractor = KnowledgeExtractor(
        api_key=cfg.llm.api_key,
        model=cfg.llm.model,
        base_url=cfg.llm.base_url,
    )
    service = KnowledgeWorkerService(cfg, engine, extractor)
    app = FastAPI()
    app.include_router(create_knowledge_worker_router(service))
    client = TestClient(app)
    headers = {"Authorization": "Bearer test-knowledge-token"}
    yield SimpleNamespace(client=client, headers=headers, service=service, extractor=extractor)
    get_config.cache_clear()


def _seed_job(engine, worker_env, tmp_path):
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4 knowledge test")
    task_id = "task_k1"
    paper_id = "pk_test01"
    with Session(engine) as session:
        session.add(User(id=1, email="u@example.com", hashed_password="x", is_active=True))
        session.add(
            Task(
                task_id=task_id,
                filename="paper.pdf",
                mode="translate",
                status=TaskStatus.COMPLETED,
                user_id=1,
                original_pdf_path=str(pdf),
            )
        )
        session.add(
            PaperKnowledge(
                id=paper_id,
                task_id=task_id,
                user_id=1,
                extraction_status="extracting",
            )
        )
        session.add(
            KnowledgeWorkerJob(
                id=f"{paper_id}:knowledge",
                task_id=task_id,
                paper_id=paper_id,
                user_id=1,
                status="queued",
            )
        )
        session.commit()


def test_worker_claim_package_and_complete(engine, worker_env, tmp_path):
    _seed_job(engine, worker_env, tmp_path)
    claim = worker_env.client.post(
        "/api/knowledge-worker/jobs/claim", headers=worker_env.headers, json={"worker_label": "test"}
    )
    assert claim.status_code == 200
    token = claim.json()["job"]["claim_token"]
    package = worker_env.client.get(f"/api/knowledge-worker/jobs/{token}/package", headers=worker_env.headers)
    assert package.status_code == 200
    with zipfile.ZipFile(BytesIO(package.content)) as archive:
        assert "original.pdf" in archive.namelist()
    knowledge = {
        "id": "pk_test01",
        "metadata": {"title": "Test Paper"},
        "structure": {"sections": []},
        "entities": [],
        "relationships": [],
        "findings": [],
        "methods": [],
        "datasets": [],
        "flashcards": [],
        "annotations": [],
        "extracted_at": "2026-01-01T00:00:00",
        "extraction_model": "test-model",
    }
    complete = worker_env.client.post(
        f"/api/knowledge-worker/jobs/{token}/complete",
        headers=worker_env.headers,
        json={"knowledge": knowledge},
    )
    assert complete.status_code == 200
    with Session(engine) as session:
        paper = session.get(PaperKnowledge, "pk_test01")
        assert paper.extraction_status == "completed"
        assert json.loads(paper.knowledge_json)["metadata"]["title"] == "Test Paper"


def test_worker_requires_token(worker_env):
    response = worker_env.client.post("/api/knowledge-worker/jobs/claim", json={"worker_label": "x"})
    assert response.status_code == 401
