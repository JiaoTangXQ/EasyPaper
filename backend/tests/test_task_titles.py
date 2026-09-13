import asyncio
import json
from types import SimpleNamespace

import fitz
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, create_engine

from app.api.deps import get_current_user
from app.api.routes import create_router
from app.models.user import User
from app.services import task_manager as manager_module
from app.services.ai_client import AIError
from app.services.pdf_downloader import DownloadResult, PdfDownloader
from app.services.reading_service import ReadingService
from app.services.task_manager import TaskManager


def pdf_bytes(title=""):
    with fitz.open() as pdf:
        pdf.new_page().insert_text((50, 80), "Example paper")
        pdf.set_metadata({"title": title})
        return pdf.tobytes()


def client_and_manager(monkeypatch, tmp_path, ai=None):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(manager_module, "engine", engine)
    manager = TaskManager()
    manager.config = SimpleNamespace(storage=SimpleNamespace(temp_dir=str(tmp_path)))

    async def process(*args, **kwargs):
        pass

    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: User(id=1, email="reader@example.com", hashed_password="hash")
    reading = (
        ReadingService(SimpleNamespace(processing=SimpleNamespace(max_concurrent=2)), engine, ai_client=ai)
        if ai
        else None
    )
    app.state.reading = reading
    app.include_router(create_router(manager, SimpleNamespace(process=process), reading))
    return TestClient(app), manager


def test_link_import_and_existing_tasks_expose_title_without_renaming_files(monkeypatch, tmp_path):
    client, manager = client_and_manager(monkeypatch, tmp_path)
    source = tmp_path / "existing.pdf"
    source.write_bytes(pdf_bytes("Existing Paper Title"))
    old = manager.create_task("2401.00001.pdf", user_id=1)
    manager.update_original_path(old.task_id, str(source))
    hidden = manager.create_task("private.pdf", user_id=2)
    manager.update_original_path(hidden.task_id, str(source))

    async def download(_self, _url):
        return DownloadResult(pdf_bytes("New Paper:\nMethods and Evidence"), "2401.00002.pdf", "application/pdf")

    monkeypatch.setattr(PdfDownloader, "download", download)
    with client:
        imported = client.post("/api/upload-url", json={"url": "https://arxiv.org/abs/2401.00002"})
        assert imported.status_code == 200
        rows = {row["task_id"]: row for row in client.get("/api/tasks").json()}
    assert set(rows) == {old.task_id, imported.json()["task_id"]}
    assert rows[old.task_id]["title"] == "Existing Paper Title"
    new = rows[imported.json()["task_id"]]
    assert new["title"] == "New Paper: Methods and Evidence"
    assert new["filename"] == "2401.00002.pdf"
    assert manager.get_task(old.task_id).filename == "2401.00001.pdf"


def test_missing_metadata_or_unreadable_file_keeps_filename_fallback(monkeypatch, tmp_path):
    client, manager = client_and_manager(monkeypatch, tmp_path)
    for name, data in [("no-title.pdf", pdf_bytes()), ("broken.pdf", b"%PDF-invalid")]:
        source = tmp_path / name
        source.write_bytes(data)
        task = manager.create_task(name, user_id=1)
        manager.update_original_path(task.task_id, str(source))
    manager.create_task("missing.pdf", user_id=1)
    response = client.get("/api/tasks")
    assert response.status_code == 200
    assert {row["filename"] for row in response.json()} == {"no-title.pdf", "broken.pdf", "missing.pdf"}
    assert all(row["title"] is None for row in response.json())


def test_changed_pdf_refreshes_cached_title(monkeypatch, tmp_path):
    client, manager = client_and_manager(monkeypatch, tmp_path)
    source = tmp_path / "paper.pdf"
    source.write_bytes(pdf_bytes("Original Title"))
    task = manager.create_task("paper.pdf", user_id=1)
    manager.update_original_path(task.task_id, str(source))
    assert client.get("/api/tasks").json()[0]["title"] == "Original Title"
    source.write_bytes(pdf_bytes("Corrected Paper Title"))
    assert client.get("/api/tasks").json()[0]["title"] == "Corrected Paper Title"


class TitleAI:
    def __init__(self):
        self.calls = []
        self.result = "有限内存下的高效学习：方法、证据与实践评估"
        self.fail = False

    async def complete_json(self, system, context, *, max_tokens):
        self.calls.append(json.loads(context))
        assert max_tokens == 512
        await asyncio.sleep(0)
        if self.fail:
            raise AIError("Example provider failure")
        return {"title_zh": self.result}


def title_task(manager, tmp_path, title="Efficient Learning with Limited Memory", user_id=1):
    source = tmp_path / f"source-{user_id}.pdf"
    source.write_bytes(pdf_bytes(title))
    task = manager.create_task("2401.00001.pdf", user_id=user_id)
    manager.update_original_path(task.task_id, str(source))
    return manager.get_task(task.task_id), source


def test_chinese_subtitle_is_cached_and_refreshed_when_original_title_changes(monkeypatch, tmp_path):
    ai = TitleAI()
    client, manager = client_and_manager(monkeypatch, tmp_path, ai)
    task, source = title_task(manager, tmp_path)
    endpoint = f"/api/tasks/{task.task_id}/title-translation"
    assert client.get("/api/tasks").json()[0]["title_zh"] is None
    assert not ai.calls  # Listing papers never waits for or starts model work.
    response = client.post(endpoint)
    assert response.status_code == 200
    assert response.json()["title_zh"] == ai.result
    assert client.post(endpoint).json() == response.json()
    assert len(ai.calls) == 1
    assert ai.calls[0] == {"title": "Efficient Learning with Limited Memory"}
    assert client.get("/api/tasks").json()[0]["title_zh"] == ai.result
    service = client.app.state.reading
    fresh = ReadingService(service.config, service.engine, ai_client=ai)
    assert asyncio.run(fresh.translate_title(task, ai.calls[0]["title"])) == ai.result
    assert len(ai.calls) == 1  # Cache survives a service restart.
    source.write_bytes(pdf_bytes("Memory-Efficient Learning: A New Evaluation"))
    assert client.get("/api/tasks").json()[0]["title_zh"] is None
    ai.result = "节省内存的学习：一项新评估"
    assert client.post(endpoint).json()["title_zh"] == ai.result
    assert len(ai.calls) == 2
    manager.delete_task(task.task_id)
    assert not fresh.cached_title_translations([task], [ai.calls[-1]["title"]])


def test_translation_failure_is_retryable_and_non_owners_cannot_generate(monkeypatch, tmp_path):
    ai = TitleAI()
    client, manager = client_and_manager(monkeypatch, tmp_path, ai)
    private, _ = title_task(manager, tmp_path, user_id=2)
    assert client.post(f"/api/tasks/{private.task_id}/title-translation").status_code == 404
    assert not ai.calls
    task, _ = title_task(manager, tmp_path)
    endpoint = f"/api/tasks/{task.task_id}/title-translation"
    ai.fail = True
    assert client.post(endpoint).status_code == 503
    assert client.get("/api/tasks").json()[0]["title_zh"] is None
    ai.fail = False
    ai.result = "Still English"
    assert client.post(endpoint).status_code == 503
    ai.result = "有限内存下的高效学习"
    assert client.post(endpoint).json()["title_zh"] == ai.result


def test_concurrent_requests_translate_once_and_chinese_titles_need_no_duplicate(monkeypatch, tmp_path):
    ai = TitleAI()
    client, manager = client_and_manager(monkeypatch, tmp_path, ai)
    task, _ = title_task(manager, tmp_path)
    service = client.app.state.reading

    async def concurrent():
        return await asyncio.gather(*(service.translate_title(task, "An English Title") for _ in range(3)))

    assert asyncio.run(concurrent()) == [ai.result] * 3
    assert len(ai.calls) == 1
    chinese, _ = title_task(manager, tmp_path, "有限内存下的高效学习")
    assert client.post(f"/api/tasks/{chinese.task_id}/title-translation").json()["title_zh"] is None
    assert len(ai.calls) == 1
