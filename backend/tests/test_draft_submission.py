from __future__ import annotations

import base64

import pytest
from sqlmodel import Session, SQLModel, create_engine

from app.models.agent import AgentTranslateRequest, DraftStatus, TranslationDraft
from app.services.translation_draft_service import TranslationDraftService


def _b64() -> str:
    return base64.b64encode(b"%PDF-1.4 test").decode("ascii")


async def _ready_draft(service: TranslationDraftService) -> str:
    created = await service.create_or_update_draft(AgentTranslateRequest(pdf_base64=_b64()))
    await service.create_or_update_draft(AgentTranslateRequest(draft_id=created.draft_id, highlight=False))
    return created.draft_id


def _service(tmp_path) -> tuple[TranslationDraftService, object]:
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    # Only the draft table is needed; avoid the task->user FK in the shared metadata.
    SQLModel.metadata.create_all(engine, tables=[TranslationDraft.__table__])
    service = TranslationDraftService(session_factory=lambda: Session(engine), temp_dir=tmp_path)
    return service, engine


@pytest.mark.asyncio
async def test_mark_submitted_persists_and_is_one_shot(tmp_path):
    service, engine = _service(tmp_path)
    draft_id = await _ready_draft(service)

    claimed = service.mark_submitted(draft_id)
    assert claimed.status == DraftStatus.SUBMITTED

    # Persisted to the DB, not just the in-memory object.
    with Session(engine) as session:
        assert session.get(TranslationDraft, draft_id).status == DraftStatus.SUBMITTED

    # A second submission of the same draft is rejected.
    with pytest.raises(ValueError):
        service.mark_submitted(draft_id)


@pytest.mark.asyncio
async def test_submitted_draft_is_not_resurrected_to_ready(tmp_path):
    service, _engine = _service(tmp_path)
    draft_id = await _ready_draft(service)
    service.mark_submitted(draft_id)

    # Re-sending the same draft_id must not flip it back to READY for re-submission.
    with pytest.raises(ValueError):
        await service.create_or_update_draft(AgentTranslateRequest(draft_id=draft_id, highlight=True))
