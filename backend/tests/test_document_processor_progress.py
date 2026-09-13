"""Exercise PDF processing through the real renderer, with only model calls stubbed."""

import asyncio
import json
import threading
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import fitz
import numpy as np
import pytest

from app.core.config import AppConfig, ProcessingConfig
from app.models.task import TaskStatus
from app.services import task_manager as task_manager_module
from app.services.document_processor import DocumentProcessor
from app.services.task_manager import TaskManager


@pytest.mark.parametrize("mode,action", [("translate", "翻译"), ("simplify", "简化")])
def test_real_pdf_pages_report_progress_and_use_configured_workers(engine, tmp_path, monkeypatch, mode, action):
    from pdf2zh import high_level
    from pdf2zh.cache import TranslationCache
    from pdf2zh.config import ConfigManager
    from pdf2zh.doclayout import DocLayoutModel
    from pdf2zh.translator import OpenAIlikedTranslator

    config = AppConfig(
        llm={"api_key": "fixture", "base_url": "https://example.invalid/v1"},
        processing={"translation_threads": 6},
        storage={"temp_dir": str(tmp_path)},
    )
    monkeypatch.setattr(task_manager_module, "engine", engine)
    monkeypatch.setattr(task_manager_module, "get_config", lambda: config)
    for key in ("OPENAILIKED_API_KEY", "OPENAILIKED_BASE_URL", "OPENAILIKED_MODEL"):
        monkeypatch.delenv(key, raising=False)
    # Do not read/write the developer's pdf2zh credentials or translation cache.
    monkeypatch.setattr(ConfigManager, "get_translator_by_name", lambda *_: None)
    monkeypatch.setattr(ConfigManager, "set_translator_by_name", lambda *_: None)
    monkeypatch.setattr(TranslationCache, "get", lambda *_: None)
    monkeypatch.setattr(TranslationCache, "set", lambda *_: None)
    font = tmp_path / "fixture-font.cff"
    font.write_bytes(fitz.Font("helv").buffer)
    monkeypatch.setattr(high_level, "download_remote_fonts", lambda _: str(font))

    manager = TaskManager()
    task = manager.create_task("fixture.pdf", mode=mode)
    page_states = []
    concurrent = peak = 0
    lock = threading.Lock()
    full_pool = threading.Event()

    def translate(_self, text):
        nonlocal concurrent, peak
        with lock:
            concurrent += 1
            peak = max(peak, concurrent)
            if concurrent == 6:
                full_pool.set()
        # A bounded wait detects the old hardcoded four workers without hanging.
        full_pool.wait(timeout=0.5)
        with lock:
            concurrent -= 1
        return text

    monkeypatch.setattr(OpenAIlikedTranslator, "do_translate", translate)

    def predict(*_args, **_kwargs):
        page_states.append(manager.get_task(task.task_id).progress)
        # Six separate paragraph regions, matching the generated PDF below.
        boxes = [SimpleNamespace(cls=0, xyxy=np.array([[15, 15 + p * 45, 390, 40 + p * 45]])) for p in range(6)]
        return [SimpleNamespace(boxes=boxes, names=["text"])]

    monkeypatch.setattr(DocLayoutModel, "load_available", lambda: SimpleNamespace(predict=predict))
    with fitz.open() as pdf:
        for page_index in range(3):
            page = pdf.new_page(width=420, height=340)
            for paragraph in range(6):
                page.insert_text(
                    (20, 30 + paragraph * 45),
                    f"Page {page_index + 1} paragraph {paragraph + 1} explains how models learn useful skills.",
                    fontsize=10,
                    fontname="tiro",
                )
        source = pdf.tobytes()

    processor = DocumentProcessor(config, manager, ai_client=SimpleNamespace())
    asyncio.run(processor.process(task.task_id, source, "fixture.pdf", mode=mode))
    result = manager.get_task(task.task_id)
    assert result.status == TaskStatus.COMPLETED, result.error
    assert result.percent == 100
    assert [state.message for state in page_states] == [f"正在{action}第 {n} / 3 页" for n in (1, 2, 3)]
    # pdf2zh's callback runs BEFORE translating that page. Never count it as done.
    assert [state.percent for state in page_states] == [30, 46, 63]
    assert all(state.status == TaskStatus.REWRITING for state in page_states)
    assert peak == 6
    with fitz.open(result.result_pdf_path) as pdf:
        assert pdf.page_count == 3
        for page in pdf:
            assert page.get_text().count("explains how models learn useful skills.") == 6
    records = json.loads(Path(result.result_pdf_path).with_suffix(".alignment.json").read_text())
    assert len(records) == 18
    assert Counter(record["page"] for record in records) == {"0": 6, "1": 6, "2": 6}
    assert all(record["source"] == record["target"] for record in records)
    assert bool(result.result_dual_pdf_path) == (mode == "translate")


@pytest.mark.parametrize("workers", [0, 17])
def test_translation_worker_count_is_bounded(workers):
    with pytest.raises(ValueError):
        ProcessingConfig(translation_threads=workers)
