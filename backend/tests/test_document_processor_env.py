from __future__ import annotations

import os

from app.core.config import AppConfig
from app.services.document_processor import DocumentProcessor
from app.services.task_manager import TaskManager


def test_pdf2zh_env_configured_from_config(monkeypatch):
    # pdf2zh reads its LLM credentials from process-global env vars. Constructing the
    # processor must publish them once, so translations don't need to lock/swap the
    # env per call (which previously serialized all concurrent translations).
    monkeypatch.delenv("OPENAILIKED_API_KEY", raising=False)

    DocumentProcessor(
        config=AppConfig(
            llm={
                "api_key": "new-key",
                "base_url": "new-url",
                "model": "new-model",
            }
        ),
        task_manager=TaskManager(),
    )

    assert os.environ["OPENAILIKED_BASE_URL"] == "new-url"
    assert os.environ["OPENAILIKED_API_KEY"] == "new-key"
    assert os.environ["OPENAILIKED_MODEL"] == "new-model"


def test_processor_has_no_global_translation_lock():
    # Regression guard: there must be no module-level lock that serializes
    # translations (the bug that made processing.max_concurrent meaningless).
    import app.services.document_processor as dp

    assert not hasattr(dp, "_PDF2ZH_ENV_LOCK")
