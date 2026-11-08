import json
import zipfile
from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.api.gloss_worker_routes import create_gloss_worker_router
from app.core.config import get_config
from app.models.gloss_worker import GlossWorkerJob
from app.models.reading import ReaderBuild, ReaderDocument, ReaderGloss, ReaderTaskLink, ReaderVersion
from app.models.task import Task, TaskStatus
from app.models.user import User
from app.services.gloss_worker_service import GlossWorkerService
from app.services.synced_reader import SyncedReader
from app.services.task_manager import TaskManager


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
  gloss_preparation: user_choice
gloss_worker:
  token: test-worker-token
storage:
  temp_dir: {tmp}/tmp
  library_dir: {tmp}/library
""".format(tmp=tmp_path),
        encoding="utf-8",
    )
    monkeypatch.setenv("APP_CONFIG_PATH", str(cfg_path))
    monkeypatch.delenv("GLOSS_WORKER_TOKEN", raising=False)
    monkeypatch.delenv("KNOWLEDGE_WORKER_TOKEN", raising=False)
    monkeypatch.delenv("EASYPAPER_KNOWLEDGE_PREPARATION", raising=False)
    get_config.cache_clear()
    cfg = get_config()
    task_manager = TaskManager(ttl_minutes=30)
    task_manager.config = cfg
    reading = SimpleNamespace(engine=engine, config=cfg, reader_processor=None)
    synced = SyncedReader(reading)
    service = GlossWorkerService(cfg, engine, task_manager, synced)
    app = FastAPI()
    app.include_router(create_gloss_worker_router(service))
    client = TestClient(app)
    headers = {"Authorization": "Bearer test-worker-token"}
    yield SimpleNamespace(client=client, headers=headers, service=service, reader=synced, task_manager=task_manager, cfg=cfg)
    get_config.cache_clear()


def _seed_job(engine, worker_env, tmp_path):
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4 test")
    document_id = "doc123"
    task_id = "task123"
    with Session(engine) as session:
        session.add(User(id=1, email="u@example.com", hashed_password="x", is_active=True))
        session.add(Task(task_id=task_id, filename="paper.pdf", mode="gloss", status=TaskStatus.REWRITING, user_id=1))
        session.add(ReaderDocument(id=document_id, user_id=1, fingerprint="abc", title="paper.pdf"))
        session.add(ReaderTaskLink(task_id=task_id, document_id=document_id))
        version = ReaderVersion(
            id=f"{document_id}:original:{'a' * 64}",
            document_id=document_id,
            kind="original",
            fingerprint="a" * 64,
            path=str(pdf),
            index_json=json.dumps({"units": [{"id": "s1", "page": 0, "text": "Energy is stored.", "chars": []}], "pages": [{}]}),
            mappings_json="[]",
        )
        session.add(version)
        session.add(ReaderBuild(id=f"{document_id}:gloss", document_id=document_id, kind="gloss", status="awaiting_worker"))
        session.add(
            GlossWorkerJob(
                id=f"{document_id}:gloss",
                task_id=task_id,
                document_id=document_id,
                user_id=1,
                status="queued",
            )
        )
        session.commit()
    worker_env.task_manager.create_task = lambda *a, **k: None
    worker_env.task_manager.get_task = lambda tid: Task(
        task_id=task_id, filename="paper.pdf", mode="gloss", status=TaskStatus.REWRITING, user_id=1
    )
    worker_env.task_manager.update_progress = lambda *a, **k: None
    worker_env.task_manager.set_error = lambda *a, **k: None


def test_worker_claim_package_and_complete(engine, worker_env, tmp_path):
    _seed_job(engine, worker_env, tmp_path)
    claim = worker_env.client.post("/api/gloss-worker/jobs/claim", headers=worker_env.headers, json={"worker_label": "test"})
    assert claim.status_code == 200
    token = claim.json()["job"]["claim_token"]
    package = worker_env.client.get(f"/api/gloss-worker/jobs/{token}/package", headers=worker_env.headers)
    assert package.status_code == 200
    with zipfile.ZipFile(BytesIO(package.content)) as archive:
        assert "original.pdf" in archive.namelist()
        assert json.loads(archive.read("index.json"))
    complete = worker_env.client.post(
        f"/api/gloss-worker/jobs/{token}/complete",
        headers=worker_env.headers,
        json={"spans": [{"id": "x", "unit_id": "s1", "text": "Energy", "zh": "能量", "category": "word", "label": "单词"}]},
    )
    assert complete.status_code == 200
    with Session(engine) as session:
        build = session.get(ReaderBuild, "doc123:gloss")
        assert build.status == "completed"
        gloss = session.get(ReaderGloss, "doc123")
        assert gloss is not None
        assert len(json.loads(gloss.spans_json)) == 1


def test_worker_requires_token(worker_env):
    response = worker_env.client.post("/api/gloss-worker/jobs/claim", json={"worker_label": "x"})
    assert response.status_code == 401
