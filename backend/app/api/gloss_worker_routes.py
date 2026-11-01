"""Authenticated APIs for trusted local gloss workers."""

from __future__ import annotations

import hmac
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from ..core.config import get_config
from ..services.gloss_worker_service import GlossWorkerService


def verify_worker_token(authorization: str | None = Header(default=None)) -> None:
    config = get_config()
    expected = config.gloss_worker.token.strip()
    if not expected:
        raise HTTPException(503, "服务器未配置本地点读处理器令牌。")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "缺少本地点读处理器认证")
    supplied = authorization.removeprefix("Bearer ").strip()
    if not hmac.compare_digest(supplied, expected):
        raise HTTPException(401, "本地点读处理器认证无效")


class ClaimRequest(BaseModel):
    worker_label: str = Field(default="local-worker", max_length=120)


class ProgressRequest(BaseModel):
    done: int = Field(ge=0)
    total: int = Field(ge=0)


class FailRequest(BaseModel):
    message: str = Field(default="本地点读准备失败", max_length=500)


class CompleteRequest(BaseModel):
    spans: list[dict[str, Any]]


def create_gloss_worker_router(service: GlossWorkerService) -> APIRouter:
    router = APIRouter(prefix="/api/gloss-worker", tags=["gloss-worker"])

    @router.post("/jobs/claim")
    async def claim_job(
        body: ClaimRequest,
        _: None = Depends(verify_worker_token),
    ) -> dict[str, Any]:
        job = service.claim_next(worker_label=body.worker_label)
        if not job:
            return {"job": None}
        return {"job": job}

    @router.post("/jobs/{claim_token}/heartbeat")
    async def heartbeat(claim_token: str, _: None = Depends(verify_worker_token)) -> dict[str, str]:
        service.extend_lease(claim_token)
        return {"status": "ok"}

    @router.get("/jobs/{claim_token}/package")
    async def download_package(claim_token: str, _: None = Depends(verify_worker_token)) -> Response:
        payload = service.build_package(claim_token)
        return Response(
            payload,
            media_type="application/zip",
            headers={"Content-Disposition": 'attachment; filename="gloss-job.zip"'},
        )

    @router.post("/jobs/{claim_token}/progress")
    async def progress(
        claim_token: str,
        body: ProgressRequest,
        _: None = Depends(verify_worker_token),
    ) -> dict[str, str]:
        service.report_progress(claim_token, body.done, body.total)
        return {"status": "ok"}

    @router.post("/jobs/{claim_token}/complete")
    async def complete(
        claim_token: str,
        body: CompleteRequest,
        _: None = Depends(verify_worker_token),
    ) -> dict[str, str]:
        service.complete(claim_token, body.spans)
        return {"status": "completed"}

    @router.post("/jobs/{claim_token}/fail")
    async def fail_job(
        claim_token: str,
        body: FailRequest,
        _: None = Depends(verify_worker_token),
    ) -> dict[str, str]:
        service.fail(claim_token, body.message)
        return {"status": "failed"}

    return router
