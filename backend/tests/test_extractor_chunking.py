from __future__ import annotations

from app.services.knowledge_extractor import KnowledgeExtractor


def _extractor() -> KnowledgeExtractor:
    return KnowledgeExtractor(api_key="x", model="m", base_url="http://example/v1")


def test_split_keeps_text_before_first_heading() -> None:
    ex = _extractor()
    full = ("ABSTRACT preamble that must not be dropped. " * 4) + (
        "METHODS body one. " * 4
    ) + ("RESULTS body two. " * 4)
    sections = [{"title": "METHODS"}, {"title": "RESULTS"}]

    chunks = ex._split_by_sections(full, sections)
    joined = "".join(chunks)

    # Text before the first matched heading must still be extracted.
    assert "ABSTRACT preamble" in joined
    assert "RESULTS body two" in joined


def test_select_chunks_not_truncated_by_section_count() -> None:
    ex = _extractor()
    # Long text whose section titles don't match -> fallback to equal chunks.
    # There are far more chunks than sections; none may be dropped.
    full = "Sentence with enough content to keep. " * 300  # ~11k chars
    sections = [{"title": "DoesNotMatch"}]

    selected = ex._select_chunks(full, sections)

    assert len(selected) > len(sections)  # not capped at the section count
    # No text is lost: the selected chunks reconstruct the whole document.
    assert "".join(selected) == full
