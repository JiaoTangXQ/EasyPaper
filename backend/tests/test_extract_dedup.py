from __future__ import annotations

from types import SimpleNamespace

from app.api.knowledge_routes import _ensure_extracting_paper


def test_extraction_is_claimed_only_once_while_in_progress(session):
    task = SimpleNamespace(task_id="t1")

    paper, started = _ensure_extracting_paper(session, task=task, user_id=1, extraction_model="m")
    assert started is True
    assert paper.extraction_status == "extracting"

    # A second trigger while extraction is in progress must not start another run.
    paper2, started2 = _ensure_extracting_paper(session, task=task, user_id=1, extraction_model="m")
    assert started2 is False
    assert paper2.id == paper.id


def test_failed_extraction_can_be_retried(session):
    task = SimpleNamespace(task_id="t2")
    paper, _ = _ensure_extracting_paper(session, task=task, user_id=1, extraction_model="m")
    paper.extraction_status = "error"
    session.add(paper)
    session.commit()

    paper2, started2 = _ensure_extracting_paper(session, task=task, user_id=1, extraction_model="m")
    assert started2 is True
    assert paper2.extraction_status == "extracting"
