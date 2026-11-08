from __future__ import annotations

import pytest
from sqlmodel import Session

from app.models.knowledge import PaperKnowledge
from app.services.knowledge_extractor import KnowledgeExtractor


@pytest.mark.asyncio
async def test_extract_start_preserves_existing_title(engine, monkeypatch):
    paper = PaperKnowledge(
        id="pk_keep",
        task_id="t1",
        user_id=1,
        title="CoworkOS: Scaling Agent Coworkers",
        extraction_status="pending",
    )
    with Session(engine) as session:
        session.add(paper)
        session.commit()

    monkeypatch.setattr("app.services.knowledge_extractor.engine", engine)
    extractor = KnowledgeExtractor(api_key="k", model="m", base_url="http://localhost")

    async def fail_pipeline(*_args, **_kwargs):
        raise RuntimeError("stop after start")

    monkeypatch.setattr(extractor, "_run_pipeline", fail_pipeline)
    monkeypatch.setattr("app.services.knowledge_extractor.parse_document", lambda _pdf: {"blocks": []})

    with pytest.raises(RuntimeError, match="stop after start"):
        await extractor.extract(b"%PDF-1.4", "t1", 1, "pk_keep")

    with Session(engine) as session:
        row = session.get(PaperKnowledge, "pk_keep")
        assert row is not None
        assert row.title == "CoworkOS: Scaling Agent Coworkers"
        assert row.extraction_status == "error"
