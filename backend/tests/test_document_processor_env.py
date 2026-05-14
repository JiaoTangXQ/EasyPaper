from __future__ import annotations

import os

from app.core.config import AppConfig
from app.services.document_processor import DocumentProcessor
from app.services.task_manager import TaskManager


def test_pdf2zh_env_is_restored_after_temporary_override(monkeypatch):
    monkeypatch.setenv("OPENAILIKED_BASE_URL", "old-url")
    monkeypatch.delenv("OPENAILIKED_API_KEY", raising=False)
    monkeypatch.setenv("OPENAILIKED_MODEL", "old-model")

    processor = DocumentProcessor(
        config=AppConfig(
            llm={
                "api_key": "new-key",
                "base_url": "new-url",
                "model": "new-model",
            }
        ),
        task_manager=TaskManager(),
    )

    previous = processor._set_pdf2zh_env()
    assert os.environ["OPENAILIKED_BASE_URL"] == "new-url"
    assert os.environ["OPENAILIKED_API_KEY"] == "new-key"
    assert os.environ["OPENAILIKED_MODEL"] == "new-model"

    processor._restore_pdf2zh_env(previous)
    assert os.environ["OPENAILIKED_BASE_URL"] == "old-url"
    assert "OPENAILIKED_API_KEY" not in os.environ
    assert os.environ["OPENAILIKED_MODEL"] == "old-model"
