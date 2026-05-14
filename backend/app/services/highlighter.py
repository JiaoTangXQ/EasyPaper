"""
高亮服务 - 使用 LLM 识别学术论文中的关键句子并在 PDF 中添加多色高亮注释
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from itertools import groupby

import fitz
import httpx

logger = logging.getLogger(__name__)


@dataclass
class HighlightSelection:
    sentence_id: str
    category: str  # "core_conclusion" | "method_innovation" | "key_data"


@dataclass
class HighlightCandidate:
    sentence_id: str
    text: str
    page_index: int
    quads: list[fitz.Quad]

    def to_metadata(self, category: str) -> dict:
        return {
            "sentence_id": self.sentence_id,
            "page_index": self.page_index,
            "text": self.text,
            "category": category,
            "rects": [[quad.rect.x0, quad.rect.y0, quad.rect.x1, quad.rect.y1] for quad in self.quads],
        }


@dataclass
class _CharBox:
    char: str
    rect: fitz.Rect | None


@dataclass
class HighlightStats:
    core_conclusions: int = 0
    method_innovations: int = 0
    key_data: int = 0
    total: int = 0
    failed_matches: int = 0

    def to_dict(self) -> dict:
        return {
            "core_conclusions": self.core_conclusions,
            "method_innovations": self.method_innovations,
            "key_data": self.key_data,
            "total": self.total,
            "failed_matches": self.failed_matches,
        }


# PyMuPDF RGB (0.0-1.0)
HIGHLIGHT_COLORS = {
    "core_conclusion": (1.0, 0.95, 0.6),
    "method_innovation": (0.7, 0.85, 1.0),
    "key_data": (0.7, 1.0, 0.7),
}

HIGHLIGHT_SYSTEM_PROMPT = (
    "You are an expert academic paper analyst. Your task is to identify key sentences "
    "from academic paper sentence candidates.\n\n"
    "Classify important sentences into exactly 3 categories:\n"
    "1. core_conclusion - Core conclusions or main findings of the research\n"
    "2. method_innovation - Methodological innovations, novel approaches, or technical contributions\n"
    "3. key_data - Key data points, experimental results, metrics, or quantitative findings\n\n"
    "RULES:\n"
    "- Return 3-8 sentence IDs per page when enough important sentences exist\n"
    "- Use only sentence_id values from the provided candidates\n"
    "- Focus on the most important sentences; skip boilerplate, references, and headers\n"
    "- If there are no notable sentences, return an empty list\n\n"
    "Respond ONLY with a JSON object:\n"
    "{\n"
    '  "highlights": [\n'
    '    {"sentence_id": "p1_s3", "category": "core_conclusion"},\n'
    '    {"sentence_id": "p1_s7", "category": "method_innovation"}\n'
    "  ]\n"
    "}\n"
)

SENTENCE_END_CHARS = frozenset("。！？!?；;")
MIN_CANDIDATE_CHARS = 12


class HighlightService:
    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str = "https://api.zhizengzeng.com/v1",
        max_concurrent_pages: int = 4,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.max_concurrent_pages = max_concurrent_pages
        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=httpx.Timeout(120.0, connect=10.0),
        )

    async def highlight_pdf(self, pdf_bytes: bytes) -> tuple[bytes, HighlightStats]:
        """主入口：提取候选句 → LLM 分类 sentence_id → 添加注释 → 返回高亮后的 PDF"""
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        try:
            candidates = self._extract_sentence_candidates(doc)
            selections = await self._classify_candidates(candidates)
            stats, _applied = self._apply_highlights(doc, candidates, selections)
            result_bytes = doc.tobytes()
            return result_bytes, stats
        except Exception as exc:
            logger.error("Highlight processing failed: %s", exc)
            return pdf_bytes, HighlightStats()
        finally:
            doc.close()

    async def highlight_pdf_with_metadata(self, pdf_bytes: bytes) -> tuple[bytes, HighlightStats, list[dict]]:
        """和 highlight_pdf 相同，但额外返回前端可展示和跳页的句子元数据。"""
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        try:
            candidates = self._extract_sentence_candidates(doc)
            selections = await self._classify_candidates(candidates)
            stats, applied = self._apply_highlights(doc, candidates, selections)
            result_bytes = doc.tobytes()
            return result_bytes, stats, applied
        except Exception as exc:
            logger.error("Highlight processing failed: %s", exc)
            return pdf_bytes, HighlightStats(), []
        finally:
            doc.close()

    def _extract_sentence_candidates(self, doc: fitz.Document) -> list[HighlightCandidate]:
        """从 PDF 字符 bbox 生成稳定句子 ID 和高亮坐标。"""
        candidates: list[HighlightCandidate] = []

        for page_index in range(doc.page_count):
            page = doc.load_page(page_index)
            chars = self._extract_page_chars(page)
            sentence_chars: list[_CharBox] = []
            page_sentence_index = 1

            for i, char_box in enumerate(chars):
                sentence_chars.append(char_box)
                prev_char = chars[i - 1].char if i > 0 else ""
                next_char = chars[i + 1].char if i + 1 < len(chars) else ""
                if self._is_sentence_end(char_box.char, prev_char, next_char):
                    candidate = self._build_candidate(page_index, page_sentence_index, sentence_chars)
                    if candidate:
                        candidates.append(candidate)
                        page_sentence_index += 1
                    sentence_chars = []

            candidate = self._build_candidate(page_index, page_sentence_index, sentence_chars)
            if candidate:
                candidates.append(candidate)

        return candidates

    def _extract_page_chars(self, page: fitz.Page) -> list[_CharBox]:
        raw = page.get_text("rawdict")
        chars: list[_CharBox] = []

        for block in raw.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                line_chars = self._extract_line_chars(line)
                if not line_chars:
                    continue
                if chars and self._needs_inserted_space(chars[-1].char, line_chars[0].char):
                    chars.append(_CharBox(" ", None))
                chars.extend(line_chars)

        return chars

    def _extract_line_chars(self, line: dict) -> list[_CharBox]:
        line_chars: list[_CharBox] = []
        for span in line.get("spans", []):
            for char in span.get("chars", []):
                value = char.get("c", "")
                if not value:
                    continue
                bbox = char.get("bbox")
                rect = fitz.Rect(bbox) if bbox else None
                line_chars.append(_CharBox(value, rect))
        return line_chars

    def _needs_inserted_space(self, previous: str, current: str) -> bool:
        if not previous or not current:
            return False
        if previous.isspace() or current.isspace():
            return False
        if previous in "-/" or previous in SENTENCE_END_CHARS:
            return False
        return previous.isascii() and current.isascii() and previous.isalnum() and current.isalnum()

    def _is_sentence_end(self, char: str, previous: str, current: str) -> bool:
        if char in SENTENCE_END_CHARS:
            return True
        if char != ".":
            return False
        if previous.isdigit() and current.isdigit():
            return False
        return True

    def _build_candidate(
        self,
        page_index: int,
        sentence_index: int,
        sentence_chars: list[_CharBox],
    ) -> HighlightCandidate | None:
        text = self._clean_sentence_text("".join(char_box.char for char_box in sentence_chars))
        if len(text) < MIN_CANDIDATE_CHARS:
            return None

        quads = self._chars_to_quads(sentence_chars)
        if not quads:
            return None

        return HighlightCandidate(
            sentence_id=f"p{page_index + 1}_s{sentence_index}",
            text=text,
            page_index=page_index,
            quads=quads,
        )

    def _clean_sentence_text(self, text: str) -> str:
        return " ".join(text.split())

    def _chars_to_quads(self, sentence_chars: list[_CharBox]) -> list[fitz.Quad]:
        rects = [
            char_box.rect for char_box in sentence_chars if char_box.rect is not None and not char_box.char.isspace()
        ]
        if not rects:
            return []

        rects.sort(key=lambda rect: (round(rect.y0, 1), rect.x0))
        line_groups: list[list[fitz.Rect]] = []
        for _line_key, group in groupby(rects, key=lambda rect: round((rect.y0 + rect.y1) / 2, 0)):
            line_groups.append(list(group))

        quads: list[fitz.Quad] = []
        for group in line_groups:
            group.sort(key=lambda rect: rect.x0)
            union = fitz.Rect(group[0])
            for rect in group[1:]:
                union |= rect
            quads.append(fitz.Quad(union.tl, union.tr, union.bl, union.br))

        return quads

    async def _classify_candidates(self, candidates: list[HighlightCandidate]) -> list[HighlightSelection]:
        if not candidates:
            return []

        chunks = self._chunk_candidates(candidates)
        semaphore = asyncio.Semaphore(self.max_concurrent_pages)

        async def classify_with_limit(chunk: list[HighlightCandidate]):
            async with semaphore:
                return await self._classify_candidate_chunk(chunk)

        selections: list[HighlightSelection] = []
        tasks = [classify_with_limit(chunk) for chunk in chunks]
        for coro in asyncio.as_completed(tasks):
            selections.extend(await coro)
        return selections

    def _chunk_candidates(
        self,
        candidates: list[HighlightCandidate],
        max_chars: int = 5000,
        max_items: int = 60,
    ) -> list[list[HighlightCandidate]]:
        chunks: list[list[HighlightCandidate]] = []
        current: list[HighlightCandidate] = []
        current_chars = 0

        for candidate in candidates:
            candidate_chars = len(candidate.text)
            if current and (current_chars + candidate_chars > max_chars or len(current) >= max_items):
                chunks.append(current)
                current = []
                current_chars = 0
            current.append(candidate)
            current_chars += candidate_chars

        if current:
            chunks.append(current)
        return chunks

    async def _classify_candidate_chunk(self, candidates: list[HighlightCandidate]) -> list[HighlightSelection]:
        max_retries = 3
        base_delay = 2
        for attempt in range(max_retries):
            try:
                return await self._do_classify_candidates(candidates)
            except Exception as exc:
                if attempt == max_retries - 1:
                    logger.error("Candidate classification failed: %s", exc)
                    return []
                delay = base_delay * (2**attempt)
                logger.warning("Candidate classification error: %s, retrying in %ds...", exc, delay)
                await asyncio.sleep(delay)
        return []

    async def _do_classify_candidates(self, candidates: list[HighlightCandidate]) -> list[HighlightSelection]:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": HIGHLIGHT_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": "Sentence candidates:\n\n"
                    + json.dumps(
                        [
                            {
                                "sentence_id": candidate.sentence_id,
                                "page": candidate.page_index + 1,
                                "text": candidate.text[:800],
                            }
                            for candidate in candidates
                        ],
                        ensure_ascii=False,
                    ),
                },
            ],
            "temperature": 0.1,
            "max_tokens": 2048,
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        response = await self._post_chat_completion(payload, headers)
        data = response.json()
        content = data["choices"][0]["message"]["content"].strip()
        parsed = self._parse_json_object(content)

        selections = []
        for item in parsed.get("highlights", []):
            sentence_id = item.get("sentence_id", "").strip()
            category = item.get("category", "")
            if sentence_id and category in HIGHLIGHT_COLORS:
                selections.append(HighlightSelection(sentence_id=sentence_id, category=category))
        return selections

    async def _post_chat_completion(self, payload: dict, headers: dict) -> httpx.Response:
        try:
            response = await self._client.post("/chat/completions", json=payload, headers=headers)
            response.raise_for_status()
            return response
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 400 and "response_format" in payload:
                fallback_payload = dict(payload)
                fallback_payload.pop("response_format", None)
                response = await self._client.post("/chat/completions", json=fallback_payload, headers=headers)
                response.raise_for_status()
                return response
            raise

    def _parse_json_object(self, content: str) -> dict:
        # Strip markdown code fences
        if content.startswith("```"):
            lines = content.split("\n")
            start_idx = 1 if lines[0].startswith("```") else 0
            end_idx = -1 if lines[-1].strip() == "```" else len(lines)
            content = "\n".join(lines[start_idx:end_idx])

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            # Fallback: try to extract JSON object from response
            start = content.find("{")
            end = content.rfind("}")
            if start != -1 and end != -1:
                parsed = json.loads(content[start : end + 1])
            else:
                raise

        return parsed

    def _apply_highlights(
        self,
        doc: fitz.Document,
        candidates: list[HighlightCandidate],
        selections: list[HighlightSelection],
    ) -> tuple[HighlightStats, list[dict]]:
        """在 PDF 中添加高亮注释"""
        stats = HighlightStats()
        applied: list[dict] = []
        candidate_map = {candidate.sentence_id: candidate for candidate in candidates}
        seen_ids: set[str] = set()

        for selection in selections:
            if selection.sentence_id in seen_ids:
                continue
            seen_ids.add(selection.sentence_id)
            candidate = candidate_map.get(selection.sentence_id)
            if not candidate or not candidate.quads or selection.category not in HIGHLIGHT_COLORS:
                stats.failed_matches += 1
                logger.debug("Could not find sentence candidate: %s", selection.sentence_id)
                continue

            page = doc.load_page(candidate.page_index)
            annot = page.add_highlight_annot(candidate.quads)
            color = HIGHLIGHT_COLORS[selection.category]
            annot.set_colors(stroke=color)
            annot.set_opacity(0.4)
            annot.set_info(title=selection.category, content=candidate.text)
            annot.update()

            self._increment_stats(stats, selection.category)
            applied.append(candidate.to_metadata(selection.category))

        return stats, applied

    def _increment_stats(self, stats: HighlightStats, category: str) -> None:
        if category == "core_conclusion":
            stats.core_conclusions += 1
        elif category == "method_innovation":
            stats.method_innovations += 1
        elif category == "key_data":
            stats.key_data += 1
        stats.total += 1

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> HighlightService:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        await self.close()
