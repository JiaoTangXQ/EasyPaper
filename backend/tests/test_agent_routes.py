from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlmodel import Session, SQLModel, create_engine

from app.api.agent_deps import require_agent_api_key
from app.api.agent_routes import create_agent_router
from app.models.agent import DraftStatus, TranslationDraft
from app.models.task import Task, TaskStatus
from app.services.translation_artifact_service import TranslationArtifactService
from app.services.translation_draft_service import TranslationDraftService
from app.services.translation_execution_service import TranslationExecutionService


class FakeTaskManager:
    def __init__(self, temp_dir: Path) -> None:
        self.config = SimpleNamespace(storage=SimpleNamespace(temp_dir=str(temp_dir)))
        self.tasks: dict[str, Task] = {}
        self._counter = 0

    def create_task(
        self,
        filename: str,
        user_id: int | None = None,
        mode: str = "translate",
        highlight: bool = False,
    ) -> Task:
        self._counter += 1
        task = Task(
            task_id=f"task-{self._counter}",
            filename=filename,
            user_id=user_id,
            mode=mode,
            highlight=highlight,
        )
        self.tasks[task.task_id] = task
        return task

    def update_original_path(self, task_id: str, path: str) -> None:
        self.tasks[task_id].original_pdf_path = path

    def get_task(self, task_id: str) -> Task | None:
        return self.tasks.get(task_id)


class ProcessorStub:
    def __init__(self, task_manager: FakeTaskManager, temp_dir: Path) -> None:
        self.task_manager = task_manager
        self.temp_dir = temp_dir
        self.calls: list[dict[str, object]] = []

    async def process(
        self,
        task_id: str,
        file_bytes: bytes,
        filename: str,
        mode: str = "translate",
        highlight: bool = False,
    ) -> None:
        self.calls.append(
            {
                "task_id": task_id,
                "filename": filename,
                "mode": mode,
                "highlight": highlight,
            }
        )
        output_path = self.temp_dir / f"{task_id}-translated.pdf"
        output_path.write_bytes(file_bytes)

        task = self.task_manager.get_task(task_id)
        assert task is not None
        task.result_pdf_path = str(output_path)
        task.status = TaskStatus.COMPLETED
        task.percent = 100
        task.message = "生成完成"


@pytest.mark.asyncio
async def test_submit_ready_draft_creates_task(tmp_path):
    task_manager = FakeTaskManager(tmp_path)
    processor = ProcessorStub(task_manager, tmp_path)

    draft_path = tmp_path / "paper.pdf"
    draft_path.write_bytes(b"%PDF-1.4 test")

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine, tables=[TranslationDraft.__table__])
    with Session(engine) as session:
        session.add(
            TranslationDraft(
                draft_id="dr_exec",
                source_type="upload",
                source_path=str(draft_path),
                filename="paper.pdf",
                highlight=False,
                status=DraftStatus.READY,
            )
        )
        session.commit()
    draft_service = TranslationDraftService(session_factory=lambda: Session(engine), temp_dir=tmp_path)
    draft = draft_service.get_draft("dr_exec")

    service = TranslationExecutionService(
        task_manager=task_manager, processor=processor, draft_service=draft_service
    )
    accepted = await service.submit_draft(draft)

    assert accepted.status == "accepted"
    assert accepted.task_id == "task-1"

    artifact_service = TranslationArtifactService(task_manager=task_manager)
    metadata = artifact_service.get_metadata(accepted.task_id)
    assert metadata.filename.endswith(".pdf")


@pytest.mark.asyncio
async def test_agent_translate_flow_returns_needs_input_then_accepts(tmp_path):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)

    task_manager = FakeTaskManager(tmp_path)
    processor = ProcessorStub(task_manager, tmp_path)
    draft_service = TranslationDraftService(
        session_factory=lambda: Session(engine),
        temp_dir=tmp_path,
        draft_ttl_minutes=30,
    )
    execution_service = TranslationExecutionService(
        task_manager=task_manager, processor=processor, draft_service=draft_service
    )
    artifact_service = TranslationArtifactService(task_manager=task_manager)

    app = FastAPI()
    app.dependency_overrides[require_agent_api_key] = lambda: None
    app.include_router(
        create_agent_router(
            draft_service=draft_service,
            execution_service=execution_service,
            artifact_service=artifact_service,
        )
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        first = await client.post(
            "/api/agent/v1/translate",
            json={"pdf_base64": "JVBERi0xLjQgdGVzdA=="},
        )
        assert first.status_code == 200
        assert first.json()["status"] == "needs_input"

        second = await client.post(
            "/api/agent/v1/translate",
            json={"draft_id": first.json()["draft_id"], "highlight": False},
        )
        assert second.status_code == 202
        assert second.json()["status"] == "accepted"

        await asyncio.sleep(0)

        status = await client.get(f"/api/agent/v1/tasks/{second.json()['task_id']}")
        assert status.status_code == 200
        assert status.json()["status"] == "completed"
        assert status.json()["artifact_ready"] is True

        artifact = await client.get(f"/api/agent/v1/tasks/{second.json()['task_id']}/artifact")
        assert artifact.status_code == 200
        assert artifact.headers["content-type"] == "application/pdf"
        assert artifact.content.startswith(b"%PDF")
