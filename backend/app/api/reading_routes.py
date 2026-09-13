"""Authenticated reading workspace; model work is explicit and cached."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlmodel import Session

from ..models.reading import ReadingState
from ..models.task import Task
from ..models.user import User
from ..services.ai_client import AIError
from ..services.document_parser import render_source
from .deps import get_current_user

logger = logging.getLogger(__name__)


class StatePatch(BaseModel):
    block_id: str | None = None
    offset: float | None = Field(default=None, ge=-10000, le=100000, allow_inf_nan=False)
    mode: Literal["chinese", "simple", "original", "bilingual"] | None = None
    font_size: int | None = Field(default=None, ge=16, le=24)
    understood: list[str] | None = Field(default=None, max_length=20000)
    bookmarked_terms: list[str] | None = Field(default=None, max_length=2000)


class ExplainRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    selection: str = Field(default="", max_length=8000)


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=8000)


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    selection: str = Field(default="", max_length=8000)
    history: list[ChatMessage] = Field(default_factory=list, max_length=12)


def create_reading_router(service) -> APIRouter:
    router = APIRouter(prefix="/api/reading", tags=["reading"])

    def owned(task_id: str, user: User) -> Task:
        with Session(service.engine) as session:
            task = session.get(Task, task_id)
        if not task or task.user_id != user.id:
            raise HTTPException(404, "论文不存在或无权访问。")
        return task

    async def document_for(task):
        try:
            return await service.document(task)
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    async def block_for(task, block_id):
        document = await document_for(task)
        block = next((b for b in document["blocks"] if b["id"] == block_id), None)
        if not block:
            raise HTTPException(404, "段落不存在，请重新载入论文。")
        return document, block

    async def model_result(awaitable):
        try:
            return await awaitable
        except AIError as exc:
            raise HTTPException(503, str(exc)) from exc
        except Exception as exc:
            logger.warning("Reading assistance failed: %s", type(exc).__name__)
            raise HTTPException(502, "辅助内容生成失败，请重试；原文和笔记仍然可读。") from exc

    @router.get("/{task_id}")
    async def workspace(task_id: str, user: User = Depends(get_current_user)):
        task = owned(task_id, user)
        await document_for(task)
        return await service.workspace(task, user.id)

    @router.patch("/{task_id}/state")
    async def save_state(task_id: str, body: StatePatch, user: User = Depends(get_current_user)):
        task = owned(task_id, user)
        document = await document_for(task)
        ids = {b["id"] for b in document["blocks"]}
        if body.block_id and body.block_id not in ids or body.understood and not set(body.understood).issubset(ids):
            raise HTTPException(422, "阅读位置不属于这篇论文。")
        with Session(service.engine) as session:
            state = session.get(ReadingState, f"{user.id}:{task_id}") or ReadingState(
                id=f"{user.id}:{task_id}", user_id=user.id, task_id=task_id
            )
            for key, value in body.model_dump(exclude_none=True).items():
                if key in {"understood", "bookmarked_terms"}:
                    setattr(state, f"{key}_json", json.dumps(list(dict.fromkeys(value)), ensure_ascii=False))
                else:
                    setattr(state, key, value)
            state.updated_at = datetime.utcnow()
            session.add(state)
            session.commit()
            session.refresh(state)
            return service.state_dict(state)

    @router.post("/{task_id}/blocks/{block_id}/aid")
    async def aid(task_id: str, block_id: str, user: User = Depends(get_current_user)):
        task = owned(task_id, user)
        document, block = await block_for(task, block_id)
        return await model_result(service.aid(task, block, document))

    @router.post("/{task_id}/blocks/{block_id}/explain")
    async def explain(task_id: str, block_id: str, body: ExplainRequest, user: User = Depends(get_current_user)):
        task = owned(task_id, user)
        document, block = await block_for(task, block_id)
        return await model_result(service.explain(task, block, document, body.question, body.selection))

    @router.post("/{task_id}/ask")
    async def ask(task_id: str, body: AskRequest, user: User = Depends(get_current_user)):
        task = owned(task_id, user)
        return await model_result(
            service.ask(
                task,
                await document_for(task),
                body.question,
                body.selection,
                history=[message.model_dump() for message in body.history],
            )
        )

    @router.get("/{task_id}/blocks/{block_id}/source")
    async def source(task_id: str, block_id: str, full_page: bool = False, user: User = Depends(get_current_user)):
        task = owned(task_id, user)
        _, block = await block_for(task, block_id)
        if not task.original_pdf_path or not Path(task.original_pdf_path).is_file():
            raise HTTPException(404, "原始 PDF 不存在，请重新导入。")
        png = await asyncio.to_thread(render_source, task.original_pdf_path, block, full_page)
        return Response(png, media_type="image/png", headers={"Cache-Control": "private, max-age=3600"})

    @router.post("/{task_id}/summary")
    async def summary(task_id: str, user: User = Depends(get_current_user)):
        task = owned(task_id, user)
        return await model_result(service.summary(task, await document_for(task)))

    @router.get("/{task_id}/export")
    async def export_reading(task_id: str, user: User = Depends(get_current_user)):
        task = owned(task_id, user)
        result = await service.workspace(task, user.id)
        return Response(
            json.dumps(result, ensure_ascii=False, indent=2),
            media_type="application/json",
            headers={"Content-Disposition": 'attachment; filename="paper-reading.json"'},
        )

    return router
