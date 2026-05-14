import base64
from pathlib import Path

import pytest
from sqlmodel import Session, SQLModel, create_engine

from app.core import db as db_module
from app.core.config import AppConfig
from app.models.agent import AgentTranslateRequest, DraftStatus, TranslationDraft
from app.services.pdf_downloader import DownloadResult
from app.services.translation_draft_service import TranslationDraftService


def test_agent_config_defaults_and_draft_model():
    config = AppConfig.model_validate(
        {
            "llm": {
                "api_key": "test-key",
                "base_url": "https://example.com/v1",
                "model": "gpt-5.2",
                "judge_model": "gpt-5.2",
            }
        }
    )

    assert config.agent.draft_ttl_minutes == 30
    assert config.agent.mcp_mount_path == "/mcp"

    draft = TranslationDraft(
        draft_id="dr_123",
        source_type="upload",
        filename="paper.pdf",
    )

    assert draft.status == DraftStatus.COLLECTING_INPUT


def test_init_db_registers_translation_draft_table():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    original_engine = db_module.engine

    try:
        db_module.engine = engine
        SQLModel.metadata.drop_all(engine)
        db_module.init_db()

        with Session(engine) as session:
            session.add(
                TranslationDraft(
                    draft_id="dr_table",
                    source_type="upload",
                    filename="paper.pdf",
                )
            )
            session.commit()
    finally:
        db_module.engine = original_engine


@pytest.mark.asyncio
async def test_create_draft_returns_needs_input_for_missing_highlight(tmp_path):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)

    service = TranslationDraftService(
        session_factory=lambda: Session(engine),
        temp_dir=tmp_path,
        draft_ttl_minutes=30,
    )
    request = AgentTranslateRequest(
        pdf_base64=base64.b64encode(b"%PDF-1.4 test").decode("ascii"),
    )

    response = await service.create_or_update_draft(request)

    assert response.status == "needs_input"
    assert response.missing_fields == ["highlight"]
    assert response.draft_id

    with Session(engine) as session:
        draft = session.get(TranslationDraft, response.draft_id)
        assert draft is not None
        assert draft.status == DraftStatus.COLLECTING_INPUT


@pytest.mark.asyncio
async def test_update_existing_draft_marks_it_ready_when_highlight_is_provided(tmp_path):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)

    service = TranslationDraftService(
        session_factory=lambda: Session(engine),
        temp_dir=tmp_path,
        draft_ttl_minutes=30,
    )
    first = await service.create_or_update_draft(
        AgentTranslateRequest(
            pdf_base64=base64.b64encode(b"%PDF-1.4 test").decode("ascii"),
        )
    )

    second = await service.create_or_update_draft(
        AgentTranslateRequest(
            draft_id=first.draft_id,
            highlight=False,
        )
    )

    assert second.status == "ready"
    assert second.draft_id == first.draft_id

    with Session(engine) as session:
        draft = session.get(TranslationDraft, first.draft_id)
        assert draft is not None
        assert draft.status == DraftStatus.READY
        assert draft.highlight is False


@pytest.mark.asyncio
async def test_create_draft_downloads_pdf_from_url(tmp_path):
    class DownloaderStub:
        async def download(self, url: str) -> DownloadResult:
            assert url == "https://example.com/paper.pdf"
            return DownloadResult(
                file_bytes=b"%PDF-1.4 from-url",
                filename="paper.pdf",
                content_type="application/pdf",
            )

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)

    service = TranslationDraftService(
        session_factory=lambda: Session(engine),
        temp_dir=tmp_path,
        draft_ttl_minutes=30,
        downloader=DownloaderStub(),
    )

    response = await service.create_or_update_draft(AgentTranslateRequest(pdf_url="https://example.com/paper.pdf"))

    assert response.status == "needs_input"

    with Session(engine) as session:
        draft = session.get(TranslationDraft, response.draft_id)
        assert draft is not None
        assert draft.source_url == "https://example.com/paper.pdf"
        assert Path(draft.source_path).read_bytes().startswith(b"%PDF")
