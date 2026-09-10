"""Disposable loopback-only browser fixture. Never imports app.main or production DB."""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace

import fitz
import uvicorn
from fastapi import FastAPI, Form
from sqlmodel import Session, SQLModel, create_engine

from app.api.deps import get_current_user
from app.api.reader_routes import create_reader_router
from app.api.reading_routes import create_reading_router
from app.core.config import LLMConfig
from app.models.task import Task, TaskStatus
from app.models.user import User
from app.services.reading_service import ReadingService

folder = Path(tempfile.mkdtemp(prefix="easypaper-reader-smoke-"))
engine = create_engine(f"sqlite:///{folder / 'test.db'}", connect_args={"check_same_thread": False})
SQLModel.metadata.create_all(engine)
EN = "The method uses 30% less memory."
ZH = "该方法将内存占用降低30%。"
SIMPLE = "This method needs 30% less memory."


def make_pdf(text, chinese=False):
    with fitz.open() as pdf:
        page = pdf.new_page(width=595, height=842)
        page.insert_text((54, 64), "Reader integration fixture", fontsize=20)
        page.insert_text((54, 110), text, fontsize=16, fontname="china-s" if chinese else "helv")
        page.insert_text((54, 145), "Saved highlights follow the meaning across versions.", fontsize=12)
        page.insert_text((54, 195), "Figure 1. A simple comparison", fontsize=13)
        for n, width in enumerate([220, 160, 110]):
            page.draw_rect(
                fitz.Rect(54, 220 + n * 35, 54 + width, 240 + n * 35), color=(0.2, 0.4, 0.3), fill=(0.75, 0.85, 0.8)
            )
        page.insert_text((54, 350), "Use the pen to annotate this diagram.", fontsize=12)
        compact_rows = [
            "第一行实验使用机器学习 ML 模型。",
            "第二行 FrontierCS 高 9.2%，PassNet 高 14.0%。",
            "第三行保存当前选择，中文和英文共享批注。",
            "第四行验证多行标注不会串到其他文字。",
        ]
        for i, row in enumerate(compact_rows):
            page.insert_text((54, 410 + i * 14), row, fontsize=10, fontname="china-s")
        second = pdf.new_page(width=595, height=842)
        second.insert_text((54, 70), "2. Limitations", fontsize=20)
        second.insert_text((54, 120), "The evaluation uses one dataset.", fontsize=14)
        return pdf.tobytes()


source, chinese, dual = folder / "source.pdf", folder / "chinese.pdf", folder / "dual.pdf"
source.write_bytes(make_pdf(EN))
chinese.write_bytes(make_pdf(ZH, True))
with fitz.open(source) as en, fitz.open(chinese) as zh, fitz.open() as both:
    for i in range(len(en)):
        both.insert_pdf(en, from_page=i, to_page=i)
        both.insert_pdf(zh, from_page=i, to_page=i)
    dual.write_bytes(both.tobytes())
with Session(engine) as session:
    session.add(User(id=1, email="reader-test@example.com", hashed_password="fixture"))
    session.add(
        Task(
            task_id="reader-fixture",
            filename="Reading and annotation fixture.pdf",
            user_id=1,
            status=TaskStatus.COMPLETED,
            original_pdf_path=str(source),
            result_pdf_path=str(chinese),
            result_dual_pdf_path=str(dual),
        )
    )
    session.commit()
config = SimpleNamespace(
    llm=LLMConfig(api_key="fixture-only"),
    processing=SimpleNamespace(max_concurrent=1),
    storage=SimpleNamespace(temp_dir=str(folder)),
)
reading = ReadingService(config, engine)
alignment_ready = asyncio.Event()
alignment_ready.set()


async def matching(_prompt, context):
    await alignment_ready.wait()
    request = json.loads(context)
    return {
        "matches": [
            {
                "id": u["id"],
                "quote": u["text"],
                "confidence": 0.99,
                "source_index": 0,
                "source_quote": (
                    request["selection"] if "selection" in request else request["source_context"][0]["sentence"]
                ),
            }
            for u in request.get("candidates", [])
            if "30%" in u["text"]
        ]
    }


reading.ask_model = matching
app = FastAPI()
app.dependency_overrides[get_current_user] = lambda: User(
    id=1, email="reader-test@example.com", hashed_password="fixture"
)
app.include_router(create_reader_router(reading))
app.include_router(create_reading_router(reading))


@app.post("/fixture/alignment")
async def alignment_gate(paused: bool):
    if paused:
        alignment_ready.clear()
    else:
        alignment_ready.set()
    return {"paused": paused}


@app.post("/api/auth/login")
def login(username: str = Form(), password: str = Form()):
    return {"access_token": "reader-smoke-fixture", "token_type": "bearer"}


@app.get("/api/tasks")
def tasks():
    return []


@app.get("/health")
def health():
    return {"status": "ok", "fixture": True}


async def prepare():
    with Session(engine) as session:
        task = session.get(Task, "reader-fixture")
    bundle = await reading.synced_reader.open_task(task, 1)
    original = next(v for v in reading.synced_reader.versions(bundle["document_id"]) if v.kind == "original")
    reading.synced_reader.snapshot(
        bundle["document_id"], "simple", make_pdf(SIMPLE), Path(original.path).parent, json.loads(original.index_json)
    )


if __name__ == "__main__":
    import shutil

    asyncio.run(prepare())
    try:
        uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("READER_SMOKE_PORT", "18080")), log_level="warning")
    finally:
        engine.dispose()
        shutil.rmtree(folder)
