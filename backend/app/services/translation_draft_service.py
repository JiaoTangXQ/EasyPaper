from __future__ import annotations

import base64
import uuid
from collections.abc import Callable
from pathlib import Path

from sqlmodel import Session

from ..models.agent import (
    AgentOption,
    AgentTranslateNeedsInput,
    AgentTranslateReady,
    AgentTranslateRequest,
    DraftStatus,
    TranslationDraft,
)
from .pdf_downloader import PdfDownloader


class TranslationDraftService:
    def __init__(
        self,
        session_factory: Callable[[], Session],
        temp_dir: str | Path,
        draft_ttl_minutes: int = 30,
        downloader: PdfDownloader | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.temp_dir = Path(temp_dir)
        self.draft_ttl_minutes = draft_ttl_minutes
        self.downloader = downloader or PdfDownloader()
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    async def create_or_update_draft(
        self, request: AgentTranslateRequest
    ) -> AgentTranslateNeedsInput | AgentTranslateReady:
        with self.session_factory() as session:
            draft = await self._load_or_create_draft(session, request)

            # A draft that was already submitted (or expired) is terminal; never
            # resurrect it to READY, or the same PDF could be translated twice.
            if draft.status in (DraftStatus.SUBMITTED, DraftStatus.EXPIRED):
                raise ValueError(f"Draft {draft.draft_id} is already {draft.status} and cannot be modified")

            if request.highlight is not None:
                draft.highlight = request.highlight

            if draft.highlight is None:
                draft.status = DraftStatus.COLLECTING_INPUT
                session.add(draft)
                session.commit()
                return AgentTranslateNeedsInput(
                    draft_id=draft.draft_id,
                    missing_fields=["highlight"],
                    question="Do you want key sentences highlighted in the translated PDF?",
                    options=[
                        AgentOption(label="Yes", value=True),
                        AgentOption(label="No", value=False),
                    ],
                )

            draft.status = DraftStatus.READY
            session.add(draft)
            session.commit()
            return AgentTranslateReady(draft_id=draft.draft_id)

    def mark_submitted(self, draft_id: str) -> TranslationDraft:
        """Atomically transition a READY draft to SUBMITTED and persist it.

        Raises ValueError if the draft is missing or not READY (e.g. already
        submitted), which is what makes submission one-shot.
        """
        with self.session_factory() as session:
            draft = session.get(TranslationDraft, draft_id)
            if not draft:
                raise ValueError(f"Draft not found: {draft_id}")
            if draft.status != DraftStatus.READY:
                raise ValueError(f"Draft {draft_id} is not ready for submission (status={draft.status})")
            draft.status = DraftStatus.SUBMITTED
            session.add(draft)
            session.commit()
            session.refresh(draft)
            session.expunge(draft)
            return draft

    def cleanup_expired_drafts(self) -> None:
        return None

    def get_draft(self, draft_id: str) -> TranslationDraft:
        with self.session_factory() as session:
            draft = session.get(TranslationDraft, draft_id)
            if not draft:
                raise ValueError(f"Draft not found: {draft_id}")
            return draft

    async def _load_or_create_draft(self, session: Session, request: AgentTranslateRequest) -> TranslationDraft:
        if request.draft_id:
            draft = session.get(TranslationDraft, request.draft_id)
            if not draft:
                raise ValueError(f"Draft not found: {request.draft_id}")
            return draft

        if request.pdf_base64:
            file_bytes = base64.b64decode(request.pdf_base64, validate=True)
            filename = "upload.pdf"
            source_type = "upload"
            source_url = None
        elif request.pdf_url:
            result = await self.downloader.download(request.pdf_url)
            file_bytes = result.file_bytes
            filename = result.filename
            source_type = "url"
            source_url = request.pdf_url
        else:
            raise ValueError("pdf_base64 or pdf_url is required")

        draft_id = uuid.uuid4().hex
        source_path = self.temp_dir / f"{draft_id}.pdf"
        source_path.write_bytes(file_bytes)

        draft = TranslationDraft(
            draft_id=draft_id,
            source_type=source_type,
            source_path=str(source_path),
            source_url=source_url,
            filename=filename,
        )
        session.add(draft)
        session.commit()
        session.refresh(draft)
        return draft
