from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from ..models.agent import (
    AgentArtifactPayload,
    AgentTaskStatus,
    AgentTranslateRequest,
    AgentTranslateToolResult,
)


def create_mcp_server(
    draft_service,
    execution_service,
    artifact_service,
    mount_path: str = "/mcp",
) -> FastMCP:
    mcp = FastMCP(
        "PDF Simplifier Agent",
        instructions="Translate PDFs into Chinese and return structured task status updates.",
        stateless_http=True,
        json_response=True,
        streamable_http_path=mount_path,
    )

    @mcp.tool(
        name="translate_pdf",
        description="Create or continue a PDF translation draft and submit it when all required fields are available.",
        structured_output=True,
    )
    async def translate_pdf(
        draft_id: str | None = None,
        pdf_url: str | None = None,
        pdf_base64: str | None = None,
        highlight: bool | None = None,
    ) -> AgentTranslateToolResult:
        request = AgentTranslateRequest(
            draft_id=draft_id,
            pdf_url=pdf_url,
            pdf_base64=pdf_base64,
            highlight=highlight,
        )
        draft_response = await draft_service.create_or_update_draft(request)
        if draft_response.status == "needs_input":
            return AgentTranslateToolResult(
                status=draft_response.status,
                draft_id=draft_response.draft_id,
                missing_fields=draft_response.missing_fields,
                question=draft_response.question,
                options=draft_response.options,
            )

        accepted = await execution_service.submit_draft(draft_service.get_draft(draft_response.draft_id))
        return AgentTranslateToolResult(
            status=accepted.status,
            draft_id=accepted.draft_id,
            task_id=accepted.task_id,
            status_url=accepted.status_url,
        )

    @mcp.tool(
        name="get_translation_task",
        description="Fetch the latest status for a translation task.",
        structured_output=True,
    )
    async def get_translation_task(task_id: str) -> AgentTaskStatus:
        return artifact_service.get_task_status(task_id)

    @mcp.tool(
        name="get_translation_artifact",
        description="Fetch the translated PDF as base64 together with metadata.",
        structured_output=True,
    )
    async def get_translation_artifact(task_id: str) -> AgentArtifactPayload:
        return artifact_service.get_payload(task_id)

    return mcp
