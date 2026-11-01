"""Poll the server and run gloss preparation locally with the configured AI provider."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import zipfile
from pathlib import Path

import httpx

from ..core.config import get_config
from ..services.ai_client import AIClient, AIError
from ..services.gloss import GLOSS_CONCURRENCY, prepare_gloss

logger = logging.getLogger(__name__)


def _concurrency() -> int:
    raw = os.getenv("EASYPAPER_GLOSS_CONCURRENCY", str(GLOSS_CONCURRENCY))
    try:
        value = int(raw)
    except ValueError:
        value = GLOSS_CONCURRENCY
    return max(1, min(value, 16))


class GlossWorkerRunner:
    def __init__(self, *, base_url: str, token: str, worker_label: str, poll_seconds: float = 5.0):
        self.base_url = base_url.rstrip("/")
        self.token = token.strip()
        self.worker_label = worker_label[:120]
        self.poll_seconds = max(1.0, poll_seconds)
        self.ai = AIClient(get_config().llm)
        self._headers = {"Authorization": f"Bearer {self.token}"}

    async def run_forever(self) -> None:
        logger.info("Gloss worker started base_url=%s label=%s concurrency=%s", self.base_url, self.worker_label, _concurrency())
        async with httpx.AsyncClient(base_url=self.base_url, timeout=httpx.Timeout(600.0, connect=30.0)) as client:
            while True:
                try:
                    handled = await self._poll_once(client)
                except httpx.HTTPError as exc:
                    logger.warning("Gloss worker request failed: %s", exc)
                    handled = False
                if not handled:
                    await asyncio.sleep(self.poll_seconds)

    async def _poll_once(self, client: httpx.AsyncClient) -> bool:
        response = await client.post(
            "/api/gloss-worker/jobs/claim",
            headers=self._headers,
            json={"worker_label": self.worker_label},
        )
        response.raise_for_status()
        payload = response.json()
        job = payload.get("job")
        if not job:
            return False
        claim_token = job["claim_token"]
        try:
            await self._process_job(client, claim_token)
        except AIError as exc:
            await self._fail(client, claim_token, str(exc))
        except Exception as exc:
            logger.exception("Gloss worker job failed")
            await self._fail(client, claim_token, f"本地点读准备失败：{exc}")
        return True

    async def _process_job(self, client: httpx.AsyncClient, claim_token: str) -> None:
        package = await client.get(
            f"/api/gloss-worker/jobs/{claim_token}/package",
            headers=self._headers,
        )
        package.raise_for_status()
        with tempfile.TemporaryDirectory(prefix="easypaper-gloss-") as temp:
            root = Path(temp)
            archive_path = root / "job.zip"
            archive_path.write_bytes(package.content)
            with zipfile.ZipFile(archive_path) as archive:
                manifest = json.loads(archive.read("manifest.json"))
                units = json.loads(archive.read("index.json"))["units"]
                resume = json.loads(archive.read("resume_spans.json"))
                archive.extract("original.pdf", root)
            pdf_path = root / "original.pdf"
            digest = manifest.get("original_pdf_sha256")
            if digest:
                import hashlib

                actual = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
                if actual != digest:
                    raise RuntimeError("PDF 校验失败，拒绝处理。")
            covered = {span.get("unit_id") for span in resume if isinstance(span, dict) and span.get("unit_id")}
            collected: list = list(resume) if isinstance(resume, list) else []

            async def on_progress(done, total):
                await client.post(
                    f"/api/gloss-worker/jobs/{claim_token}/progress",
                    headers=self._headers,
                    json={"done": done, "total": total},
                )
                await client.post(
                    f"/api/gloss-worker/jobs/{claim_token}/heartbeat",
                    headers=self._headers,
                )

            async def on_batch(produced):
                collected.extend(produced)

            spans = await prepare_gloss(
                self.ai,
                units,
                on_progress,
                on_batch=on_batch,
                skip_ids=covered,
                concurrency=_concurrency(),
            )
            _ = spans
            complete = await client.post(
                f"/api/gloss-worker/jobs/{claim_token}/complete",
                headers=self._headers,
                json={"spans": collected},
            )
            complete.raise_for_status()
            logger.info(
                "Uploaded gloss result task=%s spans=%d",
                manifest.get("task_id"),
                len(collected),
            )

    async def _fail(self, client: httpx.AsyncClient, claim_token: str, message: str) -> None:
        try:
            await client.post(
                f"/api/gloss-worker/jobs/{claim_token}/fail",
                headers=self._headers,
                json={"message": message[:500]},
            )
        except httpx.HTTPError:
            logger.exception("Failed to report gloss worker failure")


def run_worker(*, base_url: str, token: str, worker_label: str, poll_seconds: float) -> int:
    if not token.strip():
        raise ValueError("GLOSS_WORKER_TOKEN 或 --token 不能为空")
    if not get_config().llm.is_configured:
        raise ValueError("本地 AI 未配置，无法在本机准备点读。请配置 API Key 或 Cursor/Codex。")
    runner = GlossWorkerRunner(
        base_url=base_url,
        token=token,
        worker_label=worker_label,
        poll_seconds=poll_seconds,
    )
    asyncio.run(runner.run_forever())
    return 0
