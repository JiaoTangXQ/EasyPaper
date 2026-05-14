from __future__ import annotations

import json

from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, create_engine

from app.models import task as task_model  # noqa: F401
from app.models import user as user_model  # noqa: F401
from app.services import task_manager as task_manager_module
from app.services.task_manager import TaskManager


def test_set_highlight_result_persists_status_stats_and_sentences(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(task_manager_module, "engine", engine)

    manager = TaskManager()
    task = manager.create_task("paper.pdf", user_id=1, mode="translate", highlight=True)
    stats = {"total": 1, "failed_matches": 1}
    sentences = [{"sentence_id": "p1_s1", "page_index": 0, "text": "测试句子。"}]

    manager.set_highlight_result(
        task.task_id,
        stats_json=json.dumps(stats),
        status="partial",
        sentences_json=json.dumps(sentences, ensure_ascii=False),
    )

    updated = manager.get_task(task.task_id)

    assert updated is not None
    assert updated.highlight_status == "partial"
    assert json.loads(updated.highlight_stats) == stats
    assert json.loads(updated.highlight_sentences) == sentences
