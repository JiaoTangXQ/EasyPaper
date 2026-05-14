from __future__ import annotations

from pathlib import Path

import fitz

from app.services.highlighter import HighlightSelection, HighlightService


def _font_kwargs() -> dict:
    candidates = [
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    ]
    fontfile = next((path for path in candidates if Path(path).exists()), None)
    if not fontfile:
        return {}
    return {"fontfile": fontfile, "fontname": "cjk"}


def _build_cross_line_chinese_pdf() -> bytes:
    doc = fitz.open()
    page = doc.new_page(width=420, height=300)
    kwargs = _font_kwargs()
    page.insert_text((40, 60), "我们提出了一种新的方法，", fontsize=12, **kwargs)
    page.insert_text((40, 80), "在多个数据集上取得了更高的准确率。", fontsize=12, **kwargs)
    page.insert_text((40, 120), "这个结果说明模型可以稳定泛化。", fontsize=12, **kwargs)
    try:
        return doc.tobytes()
    finally:
        doc.close()


def test_extract_sentence_candidates_merges_chinese_sentence_across_line_break():
    service = HighlightService(api_key="test", model="test")
    doc = fitz.open(stream=_build_cross_line_chinese_pdf(), filetype="pdf")
    try:
        candidates = service._extract_sentence_candidates(doc)
    finally:
        doc.close()

    target = next(candidate for candidate in candidates if "更高的准确率" in candidate.text)

    assert target.text == "我们提出了一种新的方法，在多个数据集上取得了更高的准确率。"
    assert target.page_index == 0
    assert len(target.quads) == 2


def test_apply_highlights_uses_sentence_id_quads_for_cross_line_sentence():
    service = HighlightService(api_key="test", model="test")
    doc = fitz.open(stream=_build_cross_line_chinese_pdf(), filetype="pdf")
    try:
        candidates = service._extract_sentence_candidates(doc)
        target = next(candidate for candidate in candidates if "更高的准确率" in candidate.text)
        stats, applied = service._apply_highlights(
            doc,
            candidates,
            [HighlightSelection(sentence_id=target.sentence_id, category="core_conclusion")],
        )
        annotations = list(doc[0].annots() or [])
    finally:
        doc.close()

    assert stats.total == 1
    assert stats.core_conclusions == 1
    assert stats.failed_matches == 0
    assert applied[0]["sentence_id"] == target.sentence_id
    assert applied[0]["text"] == target.text
    assert len(annotations) == 1


def test_apply_highlights_counts_unknown_sentence_ids_as_failed_matches():
    service = HighlightService(api_key="test", model="test")
    doc = fitz.open(stream=_build_cross_line_chinese_pdf(), filetype="pdf")
    try:
        candidates = service._extract_sentence_candidates(doc)
        stats, applied = service._apply_highlights(
            doc,
            candidates,
            [HighlightSelection(sentence_id="missing-sentence", category="key_data")],
        )
        annotations = list(doc[0].annots() or [])
    finally:
        doc.close()

    assert stats.total == 0
    assert stats.failed_matches == 1
    assert applied == []
    assert annotations == []
