from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from sqlmodel import Session, SQLModel, create_engine

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

    async def process(
        self,
        task_id: str,
        file_bytes: bytes,
        filename: str,
        mode: str = "translate",
        highlight: bool = False,
    ) -> None:
        output_path = self.temp_dir / f"{task_id}-translated.pdf"
        output_path.write_bytes(file_bytes)

        task = self.task_manager.get_task(task_id)
        assert task is not None
        task.result_pdf_path = str(output_path)
        task.status = TaskStatus.COMPLETED
        task.percent = 100
        task.message = "生成完成"


def build_agent_app(tmp_path: Path) -> FastAPI:
    from app.mcp.server import create_mcp_server

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

    mcp_server = create_mcp_server(
        draft_service=draft_service,
        execution_service=execution_service,
        artifact_service=artifact_service,
        mount_path="/mcp",
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        async with mcp_server.session_manager.run():
            yield

    app = FastAPI(lifespan=lifespan)
    app.router.routes.extend(mcp_server.streamable_http_app().routes)
    return app


async def list_tools(app: FastAPI) -> list[str]:
    server_url = "http://127.0.0.1:8000"
    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url=server_url) as client:
            async with streamable_http_client(
                f"{server_url}/mcp",
                http_client=client,
            ) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    return [tool.name for tool in tools.tools]


@pytest.mark.asyncio
async def test_mcp_server_exposes_translation_tools(tmp_path):
    app = build_agent_app(tmp_path)

    tool_names = await list_tools(app)

    assert "translate_pdf" in tool_names
    assert "get_translation_task" in tool_names
    assert "get_translation_artifact" in tool_names


@pytest.mark.asyncio
async def test_mcp_translate_flow_returns_status_and_artifact(tmp_path):
    app = build_agent_app(tmp_path)
    server_url = "http://127.0.0.1:8000"
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url=server_url) as client:
            async with streamable_http_client(
                f"{server_url}/mcp",
                http_client=client,
            ) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()

                    first = await session.call_tool(
                        "translate_pdf",
                        {"pdf_base64": "JVBERi0xLjQgdGVzdA=="},
                    )
                    assert first.structuredContent["status"] == "needs_input"

                    second = await session.call_tool(
                        "translate_pdf",
                        {
                            "draft_id": first.structuredContent["draft_id"],
                            "highlight": False,
                        },
                    )
                    assert second.structuredContent["status"] == "accepted"

                    await asyncio.sleep(0)

                    status = await session.call_tool(
                        "get_translation_task",
                        {"task_id": second.structuredContent["task_id"]},
                    )
                    assert status.structuredContent["status"] == "completed"
                    assert status.structuredContent["artifact_ready"] is True

                    artifact = await session.call_tool(
                        "get_translation_artifact",
                        {"task_id": second.structuredContent["task_id"]},
                    )
                    assert artifact.structuredContent["content_type"] == "application/pdf"
                    assert artifact.structuredContent["pdf_base64"].startswith("JVBER")
