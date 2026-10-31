import asyncio
import json
import logging
import shutil
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel
from sqlmodel import Session
from slowapi import Limiter
from slowapi.util import get_remote_address

from ..core.config import get_config
from ..core.db import get_session
from ..models.task import TaskStatus
from ..models.user import User
from ..services.ai_client import AIError
from ..services.document_processor import DocumentProcessor
from ..services.job_queue import JobQueue
from ..services.paper_summarizer import PaperSummarizer
from ..services.pdf_downloader import PdfDownloader
from ..services.pdf_metadata import pdf_title
from ..services.pdf_validation import validate_pdf
from ..services.synced_reader import GlossImportError
from ..services.task_manager import TaskManager
from .deps import get_current_user

logger = logging.getLogger(__name__)


class UploadUrlRequest(BaseModel):
    url: str
    mode: str = "translate"
    highlight: bool = False


IMPORT_MODES = {"translate", "simplify", "gloss"}


def create_router(
    task_manager: TaskManager, processor: DocumentProcessor, reading_service=None, job_queue=None
) -> APIRouter:
    router = APIRouter(prefix="/api", tags=["documents"])
    cfg = get_config()
    _max_bytes = cfg.processing.max_upload_mb * 1024 * 1024
    _semaphore = getattr(processor, "pdf_slots", asyncio.Semaphore(cfg.processing.max_concurrent))
    limiter = Limiter(key_func=get_remote_address)
    running: dict[str, asyncio.Task] = {}
    queue = job_queue or JobQueue(cfg.processing)

    async def upload_slot(user: User = Depends(get_current_user)):
        folder = Path(cfg.storage.temp_dir)
        folder.mkdir(parents=True, exist_ok=True)
        if shutil.disk_usage(folder).free < cfg.security.min_free_disk_mb * 1024 * 1024:
            raise HTTPException(507, "服务器存储空间不足，请联系管理员")
        with queue.reserve(user.id) as start:
            yield start

    def launch(task, start):
        async def prepare_imported_gloss(current):
            task_id = current.task_id
            reader = getattr(reading_service, "synced_reader", None) if reading_service else None
            if reader is None:
                task_manager.set_error(task_id, "原文点读暂时不可用，请稍后重试。")
                return

            def report(status, percent, message):
                task_manager.update_progress(task_id, status, percent, message)

            async def on_batch(done, total):
                percent = 20 + int(75 * done / max(total, 1))
                await asyncio.to_thread(
                    report, TaskStatus.REWRITING, min(percent, 95), f"正在准备点读释义（{done}/{total}）"
                )

            report(TaskStatus.PARSING, 12, "正在索引原文…")
            paper = SimpleNamespace(
                task_id=current.task_id,
                user_id=current.user_id,
                filename=current.filename,
                mode=current.mode,
                original_pdf_path=current.original_pdf_path,
                result_pdf_path=current.result_pdf_path,
                result_dual_pdf_path=current.result_dual_pdf_path,
            )
            try:
                await reader.prepare_gloss_for_task(paper, on_batch)
            except GlossImportError as exc:
                task_manager.set_error(task_id, str(exc))
                return
            except AIError:
                logger.exception("原文点读准备超时: %s", task_id)
                task_manager.set_error(task_id, "点读释义准备超时，已写好的部分会保留。请重试，会从停下的地方继续。")
                return
            except Exception:
                logger.exception("原文点读准备失败: %s", task_id)
                task_manager.set_error(task_id, "原文点读没有准备完成，请重试。原文仍可阅读。")
                return
            report(TaskStatus.COMPLETED, 100, "原文点读已准备好")

        async def process():
            async with _semaphore:
                current = task_manager.get_task(task.task_id)
                if not current or current.status == TaskStatus.CANCELLED:
                    return
                if current.mode == "gloss":
                    await prepare_imported_gloss(current)
                    return
                await processor.process(
                    task.task_id,
                    Path(current.original_pdf_path).read_bytes(),
                    task.filename,
                    mode=task.mode,
                    highlight=task.highlight,
                )

        run = start(process())
        running[task.task_id] = run
        run.add_done_callback(lambda _: running.pop(task.task_id, None))

    @router.post("/upload")
    @limiter.limit("10/minute")
    async def upload_pdf(
        request: Request,
        file: UploadFile = File(...),
        mode: str = Form("translate"),
        highlight: bool = Form(False),
        user: User = Depends(get_current_user),
        start: Any = Depends(upload_slot),
    ) -> dict[str, Any]:
        if mode not in IMPORT_MODES:
            raise HTTPException(status_code=400, detail="mode must be 'translate', 'simplify', or 'gloss'")
        if mode == "gloss":
            highlight = False
        if file.content_type not in {"application/pdf", "application/octet-stream"}:
            raise HTTPException(status_code=400, detail="仅支持PDF文件")
        file_bytes = await file.read(_max_bytes + 1)
        await file.close()
        if not file_bytes:
            raise HTTPException(status_code=400, detail="文件内容为空")
        if len(file_bytes) > _max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"文件大小超过限制（最大 {cfg.processing.max_upload_mb}MB）",
            )

        await asyncio.to_thread(validate_pdf, file_bytes, cfg.processing.max_pages)
        task = task_manager.create_task(
            file.filename or "document.pdf", user_id=user.id, mode=mode, highlight=highlight
        )

        # Save original file
        original_path = Path(task_manager.config.storage.temp_dir) / f"{task.task_id}_original.pdf"
        with open(original_path, "wb") as f:
            f.write(file_bytes)

        # Update task with original path
        task_manager.update_original_path(task.task_id, str(original_path))

        launch(task, start)

        return {"task_id": task.task_id}

    @router.post("/upload-url")
    @limiter.limit("10/minute")
    async def upload_from_url(
        request: Request,
        body: UploadUrlRequest,
        user: User = Depends(get_current_user),
        start: Any = Depends(upload_slot),
    ) -> dict[str, Any]:
        if body.mode not in IMPORT_MODES:
            raise HTTPException(status_code=400, detail="mode must be 'translate', 'simplify', or 'gloss'")
        if body.mode == "gloss":
            body.highlight = False
        if not body.url.strip():
            raise HTTPException(status_code=400, detail="URL is required")

        downloader = PdfDownloader(max_download_mb=cfg.processing.max_upload_mb)
        try:
            result = await downloader.download(body.url)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except httpx.HTTPStatusError as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Failed to download PDF: HTTP {exc.response.status_code}",
            ) from exc
        except (httpx.TimeoutException, TimeoutError) as exc:
            raise HTTPException(status_code=504, detail="Download timed out") from exc
        except Exception as exc:
            logger.exception("Unexpected error downloading PDF from URL")
            raise HTTPException(status_code=502, detail=f"Download failed: {exc}") from exc

        file_bytes = result.file_bytes
        filename = result.filename

        if len(file_bytes) > _max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"文件大小超过限制（最大 {cfg.processing.max_upload_mb}MB）",
            )

        await asyncio.to_thread(validate_pdf, file_bytes, cfg.processing.max_pages)
        task = task_manager.create_task(filename, user_id=user.id, mode=body.mode, highlight=body.highlight)

        original_path = Path(task_manager.config.storage.temp_dir) / f"{task.task_id}_original.pdf"
        with open(original_path, "wb") as f:
            f.write(file_bytes)

        task_manager.update_original_path(task.task_id, str(original_path))

        launch(task, start)

        return {"task_id": task.task_id}

    @router.get("/tasks")
    async def list_tasks(
        user: User = Depends(get_current_user), session: Session = Depends(get_session)
    ) -> list[dict[str, Any]]:
        # The dashboard polls this every 2 seconds and aborts the previous call.
        # Those cancelled requests kept running and held a pooled connection each.
        user_id = user.id
        session.close()
        tasks = task_manager.list_tasks(user_id=user_id)
        reading = task_manager.reading_overview(user_id)
        titles = await asyncio.to_thread(lambda: [pdf_title(t.original_pdf_path) for t in tasks])
        translated_titles = reading_service.cached_title_translations(tasks, titles) if reading_service else {}
        return [
            {
                "task_id": t.task_id,
                "filename": t.filename,
                "title": title,
                "title_zh": translated_titles.get(t.task_id),
                "status": t.status,
                "created_at": t.created_at,
                "percent": t.percent,
                "message": t.message,
                "mode": t.mode,
                "highlight": t.highlight,
                "reading": reading.get(t.task_id),
                "can_read": bool(t.original_pdf_path and Path(t.original_pdf_path).is_file()),
                "highlight_status": t.highlight_status,
                "has_dual_pdf": bool(t.result_dual_pdf_path and Path(t.result_dual_pdf_path).exists()),
            }
            for t, title in zip(tasks, titles, strict=False)
        ]

    @router.post("/tasks/{task_id}/title-translation")
    async def translate_title(
        task_id: str, user: User = Depends(get_current_user), session: Session = Depends(get_session)
    ) -> dict[str, Any]:
        user_id = user.id
        session.close()
        task = task_manager.get_task(task_id)
        if not task or task.user_id != user_id:
            raise HTTPException(status_code=404, detail="论文不存在或无权访问。")
        title = await asyncio.to_thread(pdf_title, task.original_pdf_path)
        if not title or len(title) > 1000:
            raise HTTPException(status_code=422, detail="暂时没有可翻译的论文标题。")
        if not reading_service:
            raise HTTPException(status_code=503, detail="标题翻译暂不可用。")
        try:
            translated = await reading_service.translate_title(task, title)
        except AIError as exc:
            raise HTTPException(status_code=503, detail="标题暂未翻译成功，请稍后重试。") from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="论文已移除。") from exc
        return {"title": title, "title_zh": translated}

    @router.get("/status/{task_id}")
    async def get_status(task_id: str, user: User = Depends(get_current_user)) -> dict[str, Any]:
        task = task_manager.get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="任务不存在")
        if task.user_id != user.id:
            raise HTTPException(status_code=403, detail="无权访问此任务")
        progress = task.progress
        result: dict[str, Any] = {
            "status": progress.status,
            "percent": progress.percent,
            "message": progress.message,
            "error": progress.error,
        }
        if task.highlight_stats:
            result["highlight_stats"] = json.loads(task.highlight_stats)
        if task.highlight_status:
            result["highlight_status"] = task.highlight_status
        if task.highlight_sentences:
            result["highlight_sentences"] = json.loads(task.highlight_sentences)
        result["has_dual_pdf"] = bool(task.result_dual_pdf_path and Path(task.result_dual_pdf_path).exists())
        return result

    @router.get("/result/{task_id}/preview", response_class=HTMLResponse)
    async def get_preview(task_id: str, user: User = Depends(get_current_user)) -> str:
        task = task_manager.get_task(task_id)
        if not task or task.status != TaskStatus.COMPLETED:
            raise HTTPException(status_code=404, detail="结果尚未生成")
        if task.user_id != user.id:
            raise HTTPException(status_code=403, detail="无权访问此任务")
        if not task.result_preview_html:
            raise HTTPException(status_code=404, detail="暂无预览")
        return task.result_preview_html

    @router.get("/result/{task_id}/pdf")
    async def download_pdf(task_id: str, format: str = "mono", user: User = Depends(get_current_user)):
        task = task_manager.get_task(task_id)
        if not task or task.status != TaskStatus.COMPLETED:
            raise HTTPException(status_code=404, detail="结果尚未生成")
        if task.user_id != user.id:
            raise HTTPException(status_code=403, detail="无权访问此任务")

        if format not in {"mono", "dual"}:
            raise HTTPException(status_code=400, detail="format must be 'mono' or 'dual'")

        result_path = task.result_pdf_path
        filename = f"simplified_{task.filename}"
        if format == "dual":
            result_path = task.result_dual_pdf_path
            filename = f"dual_{task.filename}"

        if not result_path or not Path(result_path).exists():
            raise HTTPException(status_code=404, detail="暂无PDF内容或文件已过期")

        return FileResponse(result_path, media_type="application/pdf", filename=filename)

    @router.delete("/tasks/{task_id}")
    async def delete_task(task_id: str, user: User = Depends(get_current_user)) -> dict[str, str]:
        task = task_manager.get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="任务不存在")
        if task.user_id != user.id:
            raise HTTPException(status_code=403, detail="无权访问此任务")
        task_manager.delete_task(task_id)
        return {"status": "deleted"}

    @router.post("/tasks/{task_id}/cancel")
    async def cancel_task(task_id: str, user: User = Depends(get_current_user)):
        task = task_manager.get_task(task_id)
        if not task or task.user_id != user.id:
            raise HTTPException(404, "任务不存在")
        if task.status == TaskStatus.COMPLETED:
            raise HTTPException(409, "PDF 已生成，无需取消。")
        task_manager.update_progress(task_id, TaskStatus.CANCELLED, task.percent, "已取消 PDF 生成，原文仍可阅读")
        return {"status": "cancelled"}

    @router.post("/tasks/{task_id}/retry")
    async def retry_task(task_id: str, user: User = Depends(get_current_user), start: Any = Depends(upload_slot)):
        task = task_manager.get_task(task_id)
        if not task or task.user_id != user.id:
            raise HTTPException(404, "任务不存在")
        if task_id in running or task.status not in {TaskStatus.ERROR, TaskStatus.CANCELLED}:
            raise HTTPException(409, "当前处理尚未结束，请稍后重试。")
        if not task.original_pdf_path or not Path(task.original_pdf_path).is_file():
            raise HTTPException(404, "原始文件不存在，请重新导入。")
        task_manager.requeue(task_id)
        launch(task, start)
        return {"task_id": task_id, "status": "pending"}

    @router.post("/summary/{task_id}")
    @limiter.limit("5/minute")
    async def generate_summary(
        request: Request,
        task_id: str,
        user: User = Depends(get_current_user),
    ) -> dict[str, Any]:
        task = task_manager.get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="任务不存在")
        if task.user_id != user.id:
            raise HTTPException(status_code=403, detail="无权访问此任务")
        if task.status != TaskStatus.COMPLETED and not (
            reading_service is not None and task.original_pdf_path and Path(task.original_pdf_path).exists()
        ):
            raise HTTPException(status_code=400, detail="论文原文尚未准备好")

        if reading_service is not None:
            try:
                return await reading_service.summary(task, await reading_service.document(task))
            except Exception as exc:
                logger.exception("Reading summary generation failed")
                raise HTTPException(status_code=502, detail="摘要生成失败，请重试") from exc

        # Return cached summary
        if task.summary_json:
            return json.loads(task.summary_json)

        # Read original PDF
        if not task.original_pdf_path or not Path(task.original_pdf_path).exists():
            raise HTTPException(status_code=404, detail="原始文件不存在或已过期")

        pdf_bytes = Path(task.original_pdf_path).read_bytes()

        summarizer = PaperSummarizer(
            api_key=cfg.llm.api_key,
            model=cfg.llm.model,
            base_url=cfg.llm.base_url,
            ai_client=processor.ai,
        )

        try:
            summary = await summarizer.summarize(pdf_bytes)
        except Exception as exc:
            logger.exception("Summary generation failed")
            raise HTTPException(status_code=500, detail="摘要生成失败，请稍后重试") from exc

        # Cache result
        task_manager.set_summary(task_id, json.dumps(summary, ensure_ascii=False))

        return summary

    @router.get("/original/{task_id}/pdf")
    async def get_original_pdf(task_id: str, user: User = Depends(get_current_user)):
        task = task_manager.get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="任务不存在")
        if task.user_id != user.id:
            raise HTTPException(status_code=403, detail="无权访问此任务")

        if not task.original_pdf_path or not Path(task.original_pdf_path).exists():
            raise HTTPException(status_code=404, detail="原始文件不存在或已过期")

        return FileResponse(task.original_pdf_path, media_type="application/pdf", filename=f"original_{task.filename}")

    return router
