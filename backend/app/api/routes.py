import asyncio
import json
import logging
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel
from slowapi import Limiter
from slowapi.util import get_remote_address

from ..core.config import get_config
from ..models.task import TaskStatus
from ..models.user import User
from ..services.background_tasks import create_tracked_task
from ..services.document_processor import DocumentProcessor
from ..services.paper_summarizer import PaperSummarizer
from ..services.pdf_downloader import PdfDownloader
from ..services.task_manager import TaskManager
from .deps import get_current_user

logger = logging.getLogger(__name__)


class UploadUrlRequest(BaseModel):
    url: str
    mode: str = "translate"
    highlight: bool = False


def create_router(task_manager: TaskManager, processor: DocumentProcessor) -> APIRouter:
    router = APIRouter(prefix="/api", tags=["documents"])
    cfg = get_config()
    _max_bytes = cfg.processing.max_upload_mb * 1024 * 1024
    _semaphore = asyncio.Semaphore(cfg.processing.max_concurrent)
    limiter = Limiter(key_func=get_remote_address)

    @router.post("/upload")
    @limiter.limit("10/minute")
    async def upload_pdf(
        request: Request,
        file: UploadFile = File(...),
        mode: str = Form("translate"),
        highlight: bool = Form(False),
        user: User = Depends(get_current_user),
    ) -> dict[str, Any]:
        if mode not in ("translate", "simplify"):
            raise HTTPException(status_code=400, detail="mode must be 'translate' or 'simplify'")
        if file.content_type not in {"application/pdf", "application/octet-stream"}:
            raise HTTPException(status_code=400, detail="仅支持PDF文件")
        file_bytes = await file.read()
        if not file_bytes:
            raise HTTPException(status_code=400, detail="文件内容为空")
        if len(file_bytes) > _max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"文件大小超过限制（最大 {cfg.processing.max_upload_mb}MB）",
            )

        task = task_manager.create_task(
            file.filename or "document.pdf", user_id=user.id, mode=mode, highlight=highlight
        )

        # Save original file
        original_path = Path(task_manager.config.storage.temp_dir) / f"{task.task_id}_original.pdf"
        with open(original_path, "wb") as f:
            f.write(file_bytes)

        # Update task with original path
        task_manager.update_original_path(task.task_id, str(original_path))

        async def _process_with_limit() -> None:
            async with _semaphore:
                await processor.process(task.task_id, file_bytes, task.filename, mode=mode, highlight=highlight)

        create_tracked_task(_process_with_limit())

        return {"task_id": task.task_id}

    @router.post("/upload-url")
    @limiter.limit("10/minute")
    async def upload_from_url(
        request: Request,
        body: UploadUrlRequest,
        user: User = Depends(get_current_user),
    ) -> dict[str, Any]:
        if body.mode not in ("translate", "simplify"):
            raise HTTPException(status_code=400, detail="mode must be 'translate' or 'simplify'")
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
        except httpx.TimeoutException as exc:
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

        task = task_manager.create_task(filename, user_id=user.id, mode=body.mode, highlight=body.highlight)

        original_path = Path(task_manager.config.storage.temp_dir) / f"{task.task_id}_original.pdf"
        with open(original_path, "wb") as f:
            f.write(file_bytes)

        task_manager.update_original_path(task.task_id, str(original_path))

        async def _process_with_limit() -> None:
            async with _semaphore:
                await processor.process(
                    task.task_id, file_bytes, task.filename, mode=body.mode, highlight=body.highlight
                )

        create_tracked_task(_process_with_limit())

        return {"task_id": task.task_id}

    @router.get("/tasks")
    async def list_tasks(user: User = Depends(get_current_user)) -> list[dict[str, Any]]:
        tasks = task_manager.list_tasks(user_id=user.id)
        return [
            {
                "task_id": t.task_id,
                "filename": t.filename,
                "status": t.status,
                "created_at": t.created_at,
                "percent": t.percent,
                "message": t.message,
                "mode": t.mode,
                "highlight": t.highlight,
                "highlight_status": t.highlight_status,
                "has_dual_pdf": bool(t.result_dual_pdf_path and Path(t.result_dual_pdf_path).exists()),
            }
            for t in tasks
        ]

    @router.get("/status/{task_id}")
    async def get_status(task_id: str) -> dict[str, Any]:
        task = task_manager.get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="任务不存在")
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
        if task.status != TaskStatus.COMPLETED:
            raise HTTPException(status_code=400, detail="任务尚未完成")

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
