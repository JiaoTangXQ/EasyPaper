from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from ..models.agent import AgentTranslateRequest
from .agent_deps import require_agent_api_key


def create_agent_router(draft_service, execution_service, artifact_service) -> APIRouter:
    router = APIRouter(prefix="/api/agent/v1", tags=["agent"])

    @router.post("/translate")
    async def translate_pdf(
        body: AgentTranslateRequest,
        _: None = Depends(require_agent_api_key),
    ):
        try:
            draft_response = await draft_service.create_or_update_draft(body)
            if draft_response.status == "needs_input":
                return draft_response
            accepted = await execution_service.submit_draft(draft_service.get_draft(draft_response.draft_id))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse(status_code=202, content=accepted.model_dump())

    @router.get("/tasks/{task_id}")
    async def get_translation_task(
        task_id: str,
        _: None = Depends(require_agent_api_key),
    ):
        try:
            return artifact_service.get_task_status(task_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get("/tasks/{task_id}/artifact")
    async def get_translation_artifact(
        task_id: str,
        _: None = Depends(require_agent_api_key),
    ):
        try:
            return artifact_service.build_file_response(task_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Artifact file not found") from exc

    return router
