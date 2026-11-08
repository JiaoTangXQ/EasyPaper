"""Poll the server and run knowledge extraction locally with the configured AI provider."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import tempfile
import zipfile
from pathlib import Path

import httpx

from ..core.config import get_config
from ..services.ai_client import AIClient, AIError
from ..services.knowledge_extractor import KnowledgeExtractor

logger = logging.getLogger(__name__)


def _concurrency() -> int:
    raw = os.getenv("EASYPAPER_KNOWLEDGE_CONCURRENCY", "6")
    try:
        value = int(raw)
    except ValueError:
        value = 6
    return max(1, min(value, 16))


class KnowledgeWorkerRunner:
    def __init__(self, *, base_url: str, token: str, worker_label: str, poll_seconds: float = 5.0):
        self.base_url = base_url.rstrip("/")
        self.token = token.strip()
        self.worker_label = worker_label[:120]
        self.poll_seconds = max(1.0, poll_seconds)
        config = get_config()
        self.extractor = KnowledgeExtractor(
            api_key=config.llm.api_key,
            model=config.llm.model,
            base_url=config.llm.base_url,
            max_concurrent=_concurrency(),
            ai_client=AIClient(config.llm),
        )
        self._headers = {"Authorization": f"Bearer {self.token}"}

    async def run_forever(self) -> None:
        logger.info(
            "Knowledge worker started base_url=%s label=%s chunk_concurrency=%s",
            self.base_url,
            self.worker_label,
            _concurrency(),
        )
        async with httpx.AsyncClient(base_url=self.base_url, timeout=httpx.Timeout(3600.0, connect=30.0)) as client:
            while True:
                try:
                    handled = await self._poll_once(client)
                except httpx.HTTPError as exc:
                    logger.warning("Knowledge worker request failed: %s", exc)
                    handled = False
                if not handled:
                    await asyncio.sleep(self.poll_seconds)

    async def _poll_once(self, client: httpx.AsyncClient) -> bool:
        response = await client.post(
            "/api/knowledge-worker/jobs/claim",
            headers=self._headers,
            json={"worker_label": self.worker_label},
        )
        response.raise_for_status()
        payload = response.json()
        job = payload.get("job")
        if not job:
            return False
        claim_token = job["claim_token"]
        heartbeat: asyncio.Task | None = None
        try:
            heartbeat = asyncio.create_task(self._heartbeat_loop(client, claim_token))
            await self._process_job(client, claim_token)
        except AIError as exc:
            await self._fail(client, claim_token, str(exc))
        except Exception as exc:
            logger.exception("Knowledge worker job failed")
            await self._fail(client, claim_token, f"本机知识整理失败：{exc}")
        finally:
            if heartbeat:
                heartbeat.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await heartbeat
        return True

    async def _heartbeat_loop(self, client: httpx.AsyncClient, claim_token: str) -> None:
        while True:
            await asyncio.sleep(60)
            await client.post(
                f"/api/knowledge-worker/jobs/{claim_token}/heartbeat",
                headers=self._headers,
            )

    async def _process_job(self, client: httpx.AsyncClient, claim_token: str) -> None:
        package = await client.get(
            f"/api/knowledge-worker/jobs/{claim_token}/package",
            headers=self._headers,
        )
        package.raise_for_status()
        with tempfile.TemporaryDirectory(prefix="easypaper-knowledge-") as temp:
            root = Path(temp)
            archive_path = root / "job.zip"
            archive_path.write_bytes(package.content)
            with zipfile.ZipFile(archive_path) as archive:
                manifest = json.loads(archive.read("manifest.json"))
                archive.extract("original.pdf", root)
            pdf_path = root / "original.pdf"
            digest = manifest.get("original_pdf_sha256")
            if digest:
                import hashlib

                actual = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
                if actual != digest:
                    raise RuntimeError("PDF 校验失败，拒绝处理。")
            paper_id = manifest["paper_id"]
            user_id = int(manifest["user_id"])

            async def on_progress(done: int, total: int) -> None:
                await client.post(
                    f"/api/knowledge-worker/jobs/{claim_token}/progress",
                    headers=self._headers,
                    json={"done": done, "total": total},
                )

            pdf_bytes = pdf_path.read_bytes()
            knowledge = await self.extractor.build_knowledge(
                pdf_bytes,
                paper_id,
                user_id,
                on_progress=on_progress,
            )
            complete = await client.post(
                f"/api/knowledge-worker/jobs/{claim_token}/complete",
                headers=self._headers,
                json={"knowledge": knowledge},
            )
            complete.raise_for_status()
            logger.info(
                "Uploaded knowledge result task=%s paper=%s",
                manifest.get("task_id"),
                paper_id,
            )

    async def _fail(self, client: httpx.AsyncClient, claim_token: str, message: str) -> None:
        try:
            await client.post(
                f"/api/knowledge-worker/jobs/{claim_token}/fail",
                headers=self._headers,
                json={"message": message[:500]},
            )
        except httpx.HTTPError:
            logger.exception("Failed to report knowledge worker failure")


def run_worker(*, base_url: str, token: str, worker_label: str, poll_seconds: float) -> int:
    if not token.strip():
        raise ValueError("KNOWLEDGE_WORKER_TOKEN 或 --token 不能为空")
    if not get_config().llm.is_configured:
        raise ValueError("本地 AI 未配置，无法在本机整理知识。请配置 API Key 或 Cursor/Codex。")
    runner = KnowledgeWorkerRunner(
        base_url=base_url,
        token=token,
        worker_label=worker_label,
        poll_seconds=poll_seconds,
    )
    asyncio.run(runner.run_forever())
    return 0
