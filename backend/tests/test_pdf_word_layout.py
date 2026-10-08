from string import Template
from types import SimpleNamespace

import fitz
import numpy as np
import pytest

from app.core.config import LLMConfig
from app.services.pdf2zh_codex import pdf2zh_backend


@pytest.fixture(autouse=True)
def isolate_pdf2zh_configuration_and_cache(monkeypatch):
    from pdf2zh.cache import TranslationCache
    from pdf2zh.config import ConfigManager

    monkeypatch.setattr(ConfigManager, "get_translator_by_name", lambda *_: None)
    monkeypatch.setattr(ConfigManager, "set_translator_by_name", lambda *_: None)
    monkeypatch.setattr(TranslationCache, "get", lambda *_: None)
    monkeypatch.setattr(TranslationCache, "set", lambda *_: None)


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


def test_cross_page_sentence_is_simplified_together_then_split_between_original_pages(tmp_path, monkeypatch):
    from pdf2zh import high_level
    from pdf2zh.translator import OpenAIlikedTranslator

    complete = (
        "RL training consists of sampling rollouts, assigning rewards, and computing gradients on weighted rollouts."
    )
    tail = "More formally, the policy gradient"
    continuation = (
        "method computes the gradient of the expected reward over rollouts y from the policy p "
        "as the expected score weighted by the reward R:"
    )
    source_pages = [f"{complete} {tail}", continuation]
    joined = " ".join(source_pages)
    simplified = (
        "RL training samples outputs, scores them, and computes gradients using the scores. "
        "The policy gradient method computes the gradient of the expected reward for outputs y from policy p "
        "by weighting the score with reward R:"
    )
    calls = []

    def rewrite(_self, text):
        calls.append(text)
        return simplified if text.strip() == joined else text

    with fitz.open() as pdf:
        for source in source_pages:
            page = pdf.new_page(width=420, height=300)
            assert page.insert_textbox(fitz.Rect(35, 35, 385, 220), source, fontsize=10, fontname="tiro") > 0
        data = pdf.tobytes()
    font = tmp_path / "fixture-font.cff"
    font.write_bytes(fitz.Font("helv").buffer)
    monkeypatch.setattr(high_level, "download_remote_fonts", lambda _lang: str(font))
    monkeypatch.setattr(OpenAIlikedTranslator, "do_translate", rewrite)
    model = SimpleNamespace(predict=lambda *_args, **_kwargs: [SimpleNamespace(boxes=[], names={})])
    records = []
    with pdf2zh_backend(LLMConfig(api_key="fixture"), records=records) as backend:
        output, _ = high_level.translate_stream(
            data,
            lang_in="en",
            lang_out="en",
            thread=2,
            model=model,
            prompt=Template("$text"),
            ignore_cache=True,
            **backend,
        )
    with fitz.open(stream=output, filetype="pdf") as pdf:
        assert len(pdf) == 2
        assert " ".join(" ".join(page.get_text().split()) for page in pdf) == simplified
        for page in pdf:
            assert page.get_text().strip()
            for word in page.get_text("words"):
                assert 34 <= word[0] < word[2] <= 386
                assert 20 <= word[1] < word[3] <= 100
    assert [text.strip() for text in calls] == [joined]
    assert " ".join(record["target"].strip() for record in records) == simplified
    assert [record["page"] for record in records] == ["0", "1"]
    assert records[0]["flow_group"] == records[1]["flow_group"]


def test_cross_page_formulas_keep_their_original_glyphs_and_pages_on_cache_hits(tmp_path, monkeypatch):
    from pdf2zh import high_level
    from pdf2zh.cache import TranslationCache
    from pdf2zh.translator import OpenAIlikedTranslator

    cache, calls = {}, []
    monkeypatch.setattr(TranslationCache, "get", lambda _self, text: cache.get(text))
    monkeypatch.setattr(TranslationCache, "set", lambda _self, text, translated: cache.__setitem__(text, translated))

    def rewrite(_self, text):
        calls.append(text)
        return "The method uses {v0} and reward {v1} to compute the gradient."

    with fitz.open() as pdf:
        for pieces in [
            [("More formally, the method utilizes ", "tiro"), ("x", "tiit"), (" and the", "tiro")],
            [("reward ", "tiro"), ("R", "tiit"), (" to compute the expected gradient.", "tiro")],
        ]:
            page = pdf.new_page(width=420, height=300)
            x = 35
            for text, fontname in pieces:
                page.insert_text((x, 50), text, fontsize=10, fontname=fontname)
                x += fitz.get_text_length(text, fontname=fontname, fontsize=10)
        data = pdf.tobytes()
    font = tmp_path / "fixture-font.cff"
    font.write_bytes(fitz.Font("helv").buffer)
    monkeypatch.setattr(high_level, "download_remote_fonts", lambda _lang: str(font))
    monkeypatch.setattr(OpenAIlikedTranslator, "do_translate", rewrite)
    model = SimpleNamespace(predict=lambda *_args, **_kwargs: [SimpleNamespace(boxes=[], names={})])
    for _ in range(2):
        records = []
        with pdf2zh_backend(LLMConfig(api_key="fixture"), records=records) as backend:
            output, _ = high_level.translate_stream(
                data,
                lang_in="en",
                lang_out="en",
                thread=2,
                model=model,
                prompt=Template("$text"),
                **backend,
            )
        with fitz.open(stream=output, filetype="pdf") as pdf:
            assert " ".join(" ".join(page.get_text().split()) for page in pdf) == (
                "The method uses x and reward R to compute the gradient."
            )
            assert "x" in pdf[0].get_text().split() and "R" not in pdf[0].get_text().split()
            assert "R" in pdf[1].get_text().split() and "x" not in pdf[1].get_text().split()
            for page in pdf:
                assert b"EASYPAPER_FLOW" not in page.read_contents()
        assert len(records) == 2
        assert [r["page"] for r in records] == ["0", "1"]
        assert all("{v0}" in r["source"] and "{v0}" in r["target"] for r in records)
        assert records[0]["flow_group"] == records[1]["flow_group"]
    assert calls == ["More formally, the method utilizes {v0} and the reward {v1} to compute the expected gradient."]


def test_layout_titles_are_not_joined_to_previous_page_fragments(tmp_path, monkeypatch):
    from pdf2zh import high_level
    from pdf2zh.translator import OpenAIlikedTranslator

    with fitz.open() as pdf:
        page = pdf.new_page(width=420, height=300)
        page.insert_text((35, 50), "The analysis continues with", fontsize=10, fontname="tiro")
        page = pdf.new_page(width=420, height=300)
        page.insert_text((35, 50), "Related work", fontsize=10, fontname="tiro")
        page.insert_text((35, 100), "Previous work studies a different policy.", fontsize=10, fontname="tiro")
        data = pdf.tobytes()
    layouts = iter(
        [
            [SimpleNamespace(cls=0, xyxy=np.array([[30, 35, 390, 60]]))],
            [
                SimpleNamespace(cls=1, xyxy=np.array([[30, 35, 390, 60]])),
                SimpleNamespace(cls=0, xyxy=np.array([[30, 85, 390, 110]])),
            ],
        ]
    )
    model = SimpleNamespace(
        predict=lambda *_args, **_kwargs: [SimpleNamespace(boxes=next(layouts), names=["plain text", "title"])]
    )
    font = tmp_path / "fixture-font.cff"
    font.write_bytes(fitz.Font("helv").buffer)
    monkeypatch.setattr(high_level, "download_remote_fonts", lambda _lang: str(font))
    monkeypatch.setattr(OpenAIlikedTranslator, "do_translate", lambda _self, text: text)
    records = []
    with pdf2zh_backend(LLMConfig(api_key="fixture"), records=records) as backend:
        high_level.translate_stream(
            data, lang_in="en", lang_out="en", thread=2, model=model, prompt=Template("$text"), **backend
        )
    assert len(records) == 3
    assert all("flow_group" not in record for record in records)
