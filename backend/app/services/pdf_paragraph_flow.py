"""Join page-spanning prose before simplification, then fit it back into its slots.

The PDF adapter collects exact pdf2zh paragraphs and rendering closures. This
planner owns only reading order, translation groups and word-boundary splitting;
pdf2zh still renders the original fonts, formula glyphs and graphics.
"""

from __future__ import annotations

import logging
import math
import re
import uuid
from asyncio import CancelledError
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from functools import cache
from types import SimpleNamespace

from .pdf_word_layout import wrap_before_word
from .simplification_guard import _sentence_ends, simplify_preserving_fragments

logger = logging.getLogger(__name__)
FLOW_KEY = "__easypaper_paragraph_flow__"
_FORMULA = re.compile(r"\{v\d+\}")


@dataclass
class TextSlot:
    id: int
    page: int
    text: str
    box: object
    page_width: float
    page_height: float
    latin: object
    noto: object
    formulas: dict[str, float]
    main_page: bool = True
    literal: str = ""
    kind: str = "text"

    @property
    def lines(self):
        return max(1, math.floor((self.box.y - self.box.y0 + 0.1) / self.box.size) + 1)

    @property
    def capacity(self):
        return max(1, (self.box.x1 - self.box.x0) * self.lines / self.box.size)

    def fits(self, text: str) -> bool:
        """Measure using the same font advances and word breaks as the renderer."""
        box = self.box
        x, line, ptr = box.x, 1, 0
        while ptr < len(text):
            word_break = wrap_before_word(text, ptr, x, box.x0, box.x1, box.size, self.latin)
            formula = _FORMULA.match(text, ptr)
            if formula:
                width = self.formulas.get(formula.group())
                if width is None:
                    return False
                char = ""
                ptr = formula.end()
            else:
                char = text[ptr]
                ptr += 1
                try:
                    latin = self.latin.to_unichr(ord(char)) == char
                except Exception:
                    latin = False
                width = (
                    self.latin.char_width(ord(char)) * box.size if latin else self.noto.char_lengths(char, box.size)[0]
                )
            if word_break or x + width > box.x1 + 0.1 * box.size:
                line += 1
                x = box.x0
            if x == box.x0 and char == " ":
                width = 0
            x += width
            if line > self.lines or x > box.x1 + 0.1 * box.size:
                return False
        return True


def _has_prose(slot):
    return bool(re.search(r"[A-Za-z]{2}", _FORMULA.sub("", slot.text)))


def _heading(slot):
    if slot.kind in {
        "title",
        "section_header",
        "section_title",
        "figure_caption",
        "table_caption",
        "formula_caption",
        "caption",
    }:
        return True
    text = slot.text.strip()
    if re.match(r"(?i)^(?:figure|table|algorithm|appendix)\s+[\dA-Z][\s.:]", text):
        return True
    if re.match(r"^(?:\d+(?:\.\d+)*\s+|\[\d+\]\s+)", text):
        return True
    words = re.findall(r"[A-Za-z]+", text)
    return bool(
        words
        and len(words) <= 12
        and not re.search(r"[.!?:,]", text)
        and (text.isupper() or all(word[0].isupper() for word in words))
    )


def _reading_order(slots):
    # Full-width blocks divide a two-column page into horizontal bands. Within
    # each band, read the left column before the right one.
    wide = [s for s in slots if s.box.x1 - s.box.x0 > s.page_width * 0.55]

    def key(slot):
        mid = (slot.box.y0 + slot.box.y1) / 2
        band = sum((other.box.y0 + other.box.y1) / 2 > mid for other in wide)
        column = int(slot.box.x0 >= slot.page_width / 2)
        return band, column, -slot.box.y1, slot.id

    return sorted(slots, key=key)


def paragraph_groups(slots: list[TextSlot]) -> list[list[TextSlot]]:
    """Link only adjacent pages' last/first body blocks, never headings or captions."""
    pages = defaultdict(list)
    margin_pages = defaultdict(set)
    for slot in slots:
        # Standalone equations are reading-order barriers. Their raw glyph text
        # distinguishes them from page numbers hidden behind formula placeholders.
        equation = _FORMULA.search(slot.text) and not re.fullmatch(r"[\d\s().-]*", slot.literal)
        if slot.main_page and (_has_prose(slot) or equation):
            pages[slot.page].append(slot)
            if slot.box.y1 > slot.page_height * 0.90 or slot.box.y0 < slot.page_height * 0.10:
                key = re.sub(r"\d+", "#", " ".join((slot.literal or slot.text).lower().split()))
                margin_pages[key].add(slot.page)
    edges = {}
    page_body = {}
    for page, candidates in pages.items():
        weighted = sorted((s.box.size, len(s.text)) for s in candidates)
        midpoint = sum(weight for _, weight in weighted) / 2
        total, body_size = 0, weighted[0][0]
        for size, weight in weighted:
            total += weight
            if total >= midpoint:
                body_size = size
                break
        body = []
        for slot in candidates:
            key = re.sub(r"\d+", "#", " ".join((slot.literal or slot.text).lower().split()))
            margin = slot.box.y1 > slot.page_height * 0.90 or slot.box.y0 < slot.page_height * 0.10
            if margin and len(margin_pages[key]) > 1:
                continue
            # Footnotes may be below the final body paragraph; headings remain
            # barriers instead of being skipped to an unrelated paragraph.
            if slot.box.size < body_size * 0.85:
                continue
            body.append(slot)
        page_body[page] = _reading_order(body)
    for page, body in page_body.items():
        following = page_body.get(page + 1, [])
        if not body or not following:
            continue
        left, right = body[-1], following[0]
        if not _has_prose(left) or not _has_prose(right):
            continue
        text = left.text.rstrip()
        ends = _sentence_ends(text)
        if ends and ends[-1] == len(text):
            continue
        if _heading(left) or _heading(right) or not 0.9 <= left.box.size / right.box.size <= 1.1:
            continue
        # A visibly indented first line is evidence of a new paragraph.
        if right.box.x - right.box.x0 > right.box.size * 0.75:
            continue
        edges[left.id] = right.id
    by_id = {slot.id: slot for slot in slots}
    incoming = set(edges.values())
    groups = []
    for slot in slots:
        if slot.id in incoming:
            continue
        group = [slot]
        while group[-1].id in edges:
            group.append(by_id[edges[group[-1].id]])
        groups.append(group)
    return groups


def _joined_source(group):
    """Give formula placeholders unique identities across page-local namespaces."""
    sources, mappings = [], []
    counter = 0
    for slot in group:
        mapping = {}
        for match in _FORMULA.finditer(slot.text):
            if match.group() not in mapping:
                mapping[match.group()] = f"{{v{counter}}}"
                counter += 1
        sources.append(_FORMULA.sub(lambda m, mapping=mapping: mapping[m.group()], slot.text).strip())
        mappings.append(mapping)
    joined = sources[0]
    for source in sources[1:]:
        joined += ("" if joined.endswith("-") else " ") + source
    return joined, sources, mappings


def split_to_slots(text: str, group: list[TextSlot], sources, mappings) -> list[str] | None:
    """Choose word breaks that fit all slots and keep each formula on its page."""
    text = " ".join(text.split())
    positions = [0, *(match.end() for match in re.finditer(r"\s+", text)), len(text)]
    expected = [Counter(_FORMULA.findall(source)) for source in sources]
    reverse = [{new: old for old, new in mapping.items()} for mapping in mappings]
    weights = [slot.capacity for slot in group]
    total_weight = sum(weights)

    @cache
    def solve(index, start):
        if index == len(group):
            return (0.0, ()) if start == len(positions) - 1 else None
        best = None
        stops = range(start + 1, len(positions)) if index < len(group) - 1 else [len(positions) - 1]
        for stop in stops:
            piece = text[positions[start] : positions[stop]].strip()
            if not piece:
                continue
            formulas = Counter(_FORMULA.findall(piece))
            if formulas - expected[index]:
                break
            local = _FORMULA.sub(lambda m: reverse[index][m.group()], piece)
            if not group[index].fits(local):
                break
            if formulas != expected[index]:
                continue
            remaining = solve(index + 1, stop)
            if remaining is None:
                continue
            # Capacity is a preference, never permission to overrun a rectangle.
            score = (len(piece) / len(text) - weights[index] / total_weight) ** 2 + remaining[0]
            if stop < len(positions) - 1 and not re.search(r"[.!?:;,]$", piece):
                score += 0.001
            if best is None or score < best[0]:
                best = score, (local, *remaining[1])
        return best

    result = solve(0, 0)
    return list(result[1]) if result else None


class ParagraphFlow:
    def __init__(self, *, thread=1, records=None, callback=None, cancellation_event=None):
        self.thread = max(1, thread)
        self.records = records
        self.callback = callback
        self.cancellation_event = cancellation_event
        self.slots = []
        self.frames = []
        self.regions = []
        self.translate = None
        self._token = uuid.uuid4().hex

    def predict(self, model, *args, **kwargs):
        predictions = model.predict(*args, **kwargs)
        result = predictions[0]
        self.regions = [
            (result.names[int(box.cls)].lower().replace(" ", "_"), tuple(float(v) for v in box.xyxy.squeeze()))
            for box in result.boxes
        ]
        return predictions

    def _block_kind(self, page, box):
        top = page.height - box.y1
        for kind, (x0, y0, x1, y1) in reversed(self.regions):
            if x0 - 1 <= box.x <= x1 + 1 and y0 - 1 <= top <= y1 + 1:
                return kind
        return "text"

    def _check_cancelled(self):
        if self.cancellation_event and self.cancellation_event.is_set():
            raise CancelledError("PDF simplification cancelled")

    def close(self):
        # Rendering closures retain page glyphs and font resources. Release them
        # even if translation or cancellation interrupts the second pass.
        self.frames.clear()
        self.slots.clear()
        self.translate = None

    def capture(self, page, texts, boxes, formula_widths, formula_glyphs, converter, render):
        from pdfminer.layout import LTPage

        self._check_cancelled()
        slots = []
        for text, box in zip(texts, boxes, strict=True):
            slot = TextSlot(
                len(self.slots),
                page.pageid,
                text,
                box,
                page.width,
                page.height,
                converter.fontmap["tiro"],
                converter.noto,
                {f"{{v{i}}}": width for i, width in enumerate(formula_widths)},
                isinstance(page, LTPage),
                _FORMULA.sub(lambda m: "".join(char.get_text() for char in formula_glyphs[int(m.group()[2:-1])]), text),
                self._block_kind(page, box) if isinstance(page, LTPage) else "text",
            )
            self.slots.append(slot)
            slots.append(slot)
        marker = f"%EASYPAPER_FLOW_{self._token}_{len(self.frames)}%"
        self.frames.append((marker, slots, render))
        self.translate = converter.translator._easypaper_raw_translate
        return marker

    def _simplify(self, group):
        self._check_cancelled()
        if len(group) == 1:
            slot = group[0]
            return [simplify_preserving_fragments(slot.text, self.translate)]
        joined, sources, mappings = _joined_source(group)
        rewritten = simplify_preserving_fragments(joined, self.translate)
        if rewritten == joined:
            return [slot.text for slot in group]
        pieces = split_to_slots(rewritten, group, sources, mappings)
        if pieces is None:
            logger.warning("Simplified paragraph does not fit its PDF slots on pages %s", [s.page + 1 for s in group])
            return [slot.text for slot in group]
        return pieces

    def finish(self, patches):
        self._check_cancelled()
        groups = paragraph_groups(self.slots)
        results = {}
        group_ids = {}
        if self.callback:
            self.callback(SimpleNamespace(stage="simplifying", n=0, total=len(groups)))
        with ThreadPoolExecutor(max_workers=self.thread) as pool:
            pending = {pool.submit(self._simplify, group): (i, group) for i, group in enumerate(groups)}
            for done, future in enumerate(as_completed(pending), 1):
                self._check_cancelled()
                group_id, group = pending[future]
                for slot, target in zip(group, future.result(), strict=True):
                    results[slot.id] = target
                    if len(group) > 1:
                        group_ids[slot.id] = str(group_id)
                if self.callback:
                    self.callback(SimpleNamespace(stage="simplifying", n=done, total=len(groups)))
        replacements = {}
        for marker, slots, render in self.frames:
            self._check_cancelled()
            replacements[marker] = render([results[s.id] for s in slots])
        if self.records is not None:
            for slot in self.slots:
                record = {"source": slot.text, "target": results[slot.id], "page": str(slot.page)}
                if slot.id in group_ids:
                    record["flow_group"] = group_ids[slot.id]
                self.records.append(record)
        marker_pattern = re.compile(rf"%EASYPAPER_FLOW_{self._token}_\d+%")
        return {key: marker_pattern.sub(lambda m: replacements[m.group()], ops) for key, ops in patches.items()}
