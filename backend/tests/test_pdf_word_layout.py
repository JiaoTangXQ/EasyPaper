from string import Template
from types import SimpleNamespace

import fitz

from app.core.config import LLMConfig
from app.services.pdf2zh_codex import pdf2zh_backend


def test_word_boundaries_in_the_actual_pdf_translation_renderer(tmp_path, monkeypatch):
    from pdf2zh import converter, high_level
    from pdf2zh.translator import OpenAIlikedTranslator

    source = "These models use carefully selected examples to learn new skills and solve useful tasks."
    rewritten = "These models understand language and perform reasoning, planning, and execution with reusable skills."
    with fitz.open() as pdf:
        p = pdf.new_page(width=220, height=200)
        p.insert_textbox(fitz.Rect(20, 20, 180, 90), source, fontsize=10, fontname="tiro")
        data = pdf.tobytes()
    font = tmp_path / "fixture-font.cff"
    font.write_bytes(fitz.Font("helv").buffer)
    monkeypatch.setattr(high_level, "download_remote_fonts", lambda _lang: str(font))
    monkeypatch.setattr(OpenAIlikedTranslator, "do_translate", lambda _self, _text: rewritten)
    model = SimpleNamespace(predict=lambda *_args, **_kwargs: [SimpleNamespace(boxes=[], names={})])
    with pdf2zh_backend(LLMConfig(api_key="fixture"), records=[]) as backend:
        output, _ = high_level.translate_stream(
            data,
            lang_in="en",
            lang_out="en",
            thread=1,
            model=model,
            prompt=Template("$text"),
            ignore_cache=True,
            **backend,
        )
    with fitz.open(stream=output, filetype="pdf") as pdf:
        lines = pdf[0].get_text().splitlines()
        assert " ".join(lines).split() == rewritten.split()
        for word in pdf[0].get_text("words"):
            assert word[0] >= 19 and word[2] <= 181
    # No installed dependency file is rewritten by the adapter.
    assert converter.TranslateConverter.receive_layout.__module__.startswith("app.services")
