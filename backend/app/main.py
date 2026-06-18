from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from sqlmodel import Session

from .api.agent_deps import MCPAuthMiddleware
from .api.agent_routes import create_agent_router
from .api.auth import router as auth_router
from .api.knowledge_routes import create_knowledge_router
from .api.routes import create_router
from .core.config import get_config
from .core.db import engine, init_db
from .core.logger import setup_logging
from .mcp.server import create_mcp_server
from .services.document_processor import DocumentProcessor
from .services.knowledge_extractor import KnowledgeExtractor
from .services.task_manager import TaskManager
from .services.translation_artifact_service import TranslationArtifactService
from .services.translation_draft_service import TranslationDraftService
from .services.translation_execution_service import TranslationExecutionService

logger = logging.getLogger(__name__)

setup_logging()
config = get_config()
task_manager = TaskManager(ttl_minutes=config.storage.cleanup_minutes)
processor = DocumentProcessor(config=config, task_manager=task_manager)
knowledge_extractor = KnowledgeExtractor(
    api_key=config.llm.api_key,
    model=config.llm.model,
    base_url=config.llm.base_url,
)
draft_service = TranslationDraftService(
    session_factory=lambda: Session(engine),
    temp_dir=config.storage.temp_dir,
    draft_ttl_minutes=config.agent.draft_ttl_minutes,
)
execution_service = TranslationExecutionService(
    task_manager=task_manager, processor=processor, draft_service=draft_service
)
artifact_service = TranslationArtifactService(task_manager=task_manager)
mcp_server = create_mcp_server(
    draft_service=draft_service,
    execution_service=execution_service,
    artifact_service=artifact_service,
    mount_path=config.agent.mcp_mount_path,
)

limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title="PDF Simplifier", version="1.0.0")
app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(status_code=429, content={"detail": "请求过于频繁，请稍后重试"})


app.add_middleware(
    CORSMiddleware,
    allow_origins=config.security.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(
    MCPAuthMiddleware,
    mount_path=config.agent.mcp_mount_path,
    api_keys=config.agent.api_keys,
)

app.include_router(auth_router, prefix="/api/auth")
app.include_router(
    create_agent_router(
        draft_service=draft_service,
        execution_service=execution_service,
        artifact_service=artifact_service,
    )
)
app.include_router(create_router(task_manager, processor))
app.include_router(create_knowledge_router(knowledge_extractor))
app.router.routes.extend(mcp_server.streamable_http_app().routes)


@app.get("/health")
async def healthcheck() -> dict:
    return {"status": "ok"}


_cleanup_task: asyncio.Task | None = None
_mcp_session_context: Any = None


@app.on_event("startup")
async def on_startup() -> None:
    global _cleanup_task, _mcp_session_context
    init_db()
    Path(config.storage.temp_dir).mkdir(parents=True, exist_ok=True)
    # Reconcile tasks orphaned by a restart (in-memory processing is gone).
    orphaned = task_manager.fail_orphaned_tasks()
    if orphaned:
        logger.info("Marked %d orphaned task(s) as errored on startup", orphaned)
    _mcp_session_context = mcp_server.session_manager.run()
    await _mcp_session_context.__aenter__()
    _cleanup_task = asyncio.create_task(run_cleanup_task())


@app.on_event("shutdown")
async def on_shutdown() -> None:
    global _mcp_session_context
    if _cleanup_task and not _cleanup_task.done():
        _cleanup_task.cancel()
        try:
            await _cleanup_task
        except asyncio.CancelledError:
            pass
    if _mcp_session_context is not None:
        await _mcp_session_context.__aexit__(None, None, None)
        _mcp_session_context = None
    # Run one final cleanup before exit
    try:
        task_manager.cleanup()
    except Exception as exc:  # noqa: BLE001
        logger.error("Final cleanup failed: %s", exc)


async def run_cleanup_task() -> None:
    while True:
        await asyncio.sleep(60 * config.storage.cleanup_minutes)
        try:
            task_manager.cleanup()
            draft_service.cleanup_expired_drafts()
        except Exception as exc:  # noqa: BLE001
            logger.error("Cleanup failed: %s", exc)
