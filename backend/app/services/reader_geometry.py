"""Ground text selections in the actual PDF; never infer a translated rectangle."""

from __future__ import annotations

import hashlib
import re
import unicodedata

import fitz


def normalized(text: str) -> str:
    value = unicodedata.normalize("NFKC", text).translate(str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"'}))
    return "".join(c for c in value if not c.isspace() and c not in "\u00ad\u200b").casefold()


CONNECTIVES = {
    "而": ("and", "but", "whereas", "while", "yet"),
    "但": ("but", "yet"),
    "但是": ("but", "yet"),
    "然而": ("however", "but", "yet"),
    "而且": ("and",),
    "以及": ("and",),
    "或": ("or",),
    "或者": ("or",),
    "不过": ("however", "but", "yet"),
    "and": ("而", "而且", "以及"),
    "but": ("但", "但是", "然而", "不过"),
    "yet": ("但", "但是", "然而", "不过"),
    "however": ("然而", "不过"),
    "whereas": ("而",),
    "while": ("而",),
    "or": ("或", "或者"),
}
CONNECTIVES = {word: (word, *translations) for word, translations in CONNECTIVES.items()}


def connective_prefix(text: str, start: int, allowed) -> tuple[str, int, str] | None:
    """Find only a clause-leading connective immediately before a proven phrase.

    start and the returned offset are in normalized text. The returned source
    prefix retains the PDF's characters. No content words are inferred.
    """
    value, offsets = "", []
    for i, char in enumerate(text):
        chunk = normalized(char)
        value += chunk
        offsets.extend([i] * len(chunk))
    for word in sorted(allowed, key=len, reverse=True):
        left = start - len(word)
        if left < 0 or value[left:start] != word:
            continue
        before = text[: offsets[left]].rstrip()
        if before and before[-1] not in ",;:，；：。.!?！？":
            continue
        end = offsets[start] if start < len(offsets) else len(text)
        return word, left, text[offsets[left] : end]
    return None


def has_explicit_negation(text: str) -> bool:
    """A conservative guard for dropped operators, not a semantic equivalence test."""
    return bool(
        re.search(
            r"\b(?:not|never|without|neither|nor|cannot)\b|\bno\b(?!\.)|\b\w+n['’]t\b|没有|并非|无法|不能|未能|不|无|未",
            text,
            re.I,
        )
    )


def restores_negation(selected: str, prior: str, revised: str) -> bool:
    """Allow a missed negation/auxiliary at a phrase boundary, never a new claim."""
    if not has_explicit_negation(selected) or has_explicit_negation(prior) or not has_explicit_negation(revised):
        return False
    before, after = normalized(prior), normalized(revised)
    if not before or after.count(before) != 1:
        return False
    extra = after.replace(before, "", 1)
    # These tokens can complete a negated predicate without adding content words.
    extra = re.sub(
        r"cannot|without|neither|never|does|were|been|being|not|nor|no|are|was|did|do|is|be|it|but|yet|没有|并非|无法|不能|未能|并|但|不|无|未",
        "",
        extra,
    )
    return not extra.strip(" .,;:!?，。；：！？'’")


def box(rect: dict) -> list[float]:
    p, s = rect["origin"], rect["size"]
    return [p["x"], p["y"], p["x"] + s["width"], p["y"] + s["height"]]


def rect(values) -> dict:
    x0, y0, x1, y1 = values
    return {"origin": {"x": x0, "y": y0}, "size": {"width": x1 - x0, "height": y1 - y0}}


def union(rects: list[dict]) -> dict:
    bounds = fitz.Rect(box(rects[0]))
    for item in rects[1:]:
        bounds |= fitz.Rect(box(item))
    return rect(bounds)


def pdf_index(data: bytes) -> dict:
    pages, units, figures = [], [], []
    with fitz.open(stream=data, filetype="pdf") as pdf:
        for page_index, page in enumerate(pdf):
            pages.append({"width": page.cropbox.width, "height": page.cropbox.height, "rotation": page.rotation})
            for info in page.get_image_info(hashes=True):
                if info["width"] >= 40 and info["height"] >= 40:
                    figures.append(
                        {
                            "page": page_index,
                            "digest": info["digest"].hex(),
                            "rect": rect(info["bbox"]),
                            "transform": list(info["transform"]),
                        }
                    )
            raw = page.get_text("rawdict", flags=fitz.TEXTFLAGS_RAWDICT & ~fitz.TEXT_PRESERVE_IMAGES)
            for block in raw["blocks"]:
                if block.get("type") != 0:
                    continue
                chars = []
                for line_index, line in enumerate(block.get("lines", [])):
                    for span in line["spans"]:
                        chars.extend(
                            {"c": c["c"], "b": [round(v, 3) for v in c["bbox"]], "l": line_index} for c in span["chars"]
                        )
                    chars.append({"c": "\n", "b": None, "l": line_index})
                text = "".join(c["c"] for c in chars)
                if not text.strip():
                    continue
                # Keep geometry frozen in the archived version, including sentence boundaries.
                for match in re.finditer(r".+?(?:[!?。！？]+|\.(?!\d)(?=\s|$)|$)", text, flags=re.S):
                    selected = chars[match.start() : match.end()]
                    if not any(c["b"] and not c["c"].isspace() for c in selected):
                        continue
                    uid = hashlib.sha256(
                        f"{page_index}:{match.start()}:{block['bbox']}:{match.group()}".encode()
                    ).hexdigest()[:24]
                    units.append({"id": uid, "page": page_index, "text": match.group().strip(), "chars": selected})
    return {"pages": pages, "units": units, "figures": figures}


def char_rects(chars: list[dict]) -> list[dict]:
    lines: dict[int, fitz.Rect] = {}
    for char in chars:
        if char["b"] and not char["c"].isspace():
            if char["l"] in lines:
                lines[char["l"]] |= fitz.Rect(char["b"])
            else:
                lines[char["l"]] = fitz.Rect(char["b"])
    return [rect(bounds) for bounds in lines.values()]


def selection(index: dict, annotation: dict) -> tuple[str, list[str]]:
    parts = selection_parts(index, annotation)
    return " ".join(p["quote"] for p in parts), [p["unit_id"] for p in parts]


def text_anchor(unit: dict, quote: str) -> dict:
    """Persist text and neighboring content; renderer coordinates are disposable."""
    text, needle = normalized(unit["text"]), normalized(quote)
    if not needle or text.count(needle) != 1:
        return {"text": quote}
    start = text.index(needle)
    end = start + len(needle)
    return {"text": quote, "prefix": text[max(0, start - 48) : start], "suffix": text[end : end + 48]}


def selection_context(sentence: str, selected: str) -> dict:
    """Keep selected and unselected meanings visibly separate in model input."""
    value, offsets = "", []
    for i, char in enumerate(sentence):
        chunk = normalized(char)
        value += chunk
        offsets.extend([i] * len(chunk))
    needle = normalized(selected)
    result = {"selected": selected, "sentence": sentence}
    if needle and value.count(needle) == 1:
        start = value.index(needle)
        left, right = offsets[start], offsets[start + len(needle) - 1] + 1
        result.update(unselected_before=sentence[:left], unselected_after=sentence[right:])
    return result


def trim_unselected_contrast(text: str, selected: str, context: list[dict] | None) -> str:
    """A selected contrast connector does not select the clause after it."""
    connector = r"\bbut\b|但是|但"
    if not context or len(context) != 1 or not re.search(r"(?:\bbut|但是|但)\s*$", selected, re.I):
        return text
    if len(re.findall(connector, selected, re.I)) != 1:
        return text
    if not selection_context(context[0]["sentence"], context[0]["selected"]).get("unselected_after", "").strip():
        return text
    match = re.search(connector, text, re.I)
    return text[: match.end()] if match else text


def reanchor_text_parts(parts: list[dict], units: list[dict]) -> list[dict]:
    """Carry verified text to a new PDF revision without carrying its old boxes."""
    result = []
    for part in parts:
        if part.get("unmatched_fragments") or not part.get("quote"):
            return []
        matches = [(unit, locate_quote(unit, part["quote"])) for unit in units]
        matches = [(unit, boxes) for unit, boxes in matches if boxes]
        if len(matches) != 1:
            return []
        unit, boxes = matches[0]
        result.append(
            {
                "unit_id": unit["id"],
                "page": unit["page"],
                "quote": part["quote"],
                "rects": boxes,
                "method": "revision-text",
                "text_anchor": text_anchor(unit, part["quote"]),
            }
        )
    return result


def selection_parts(index: dict, annotation: dict) -> list[dict]:
    boxes = [fitz.Rect(box(r)) for r in annotation.get("segmentRects", []) or [annotation["rect"]]]
    parts = []
    for unit in index["units"]:
        if unit["page"] != annotation["pageIndex"]:
            continue
        chars = [
            c
            for c in unit["chars"]
            if c["b"] and any(b.contains((fitz.Rect(c["b"]).tl + fitz.Rect(c["b"]).br) / 2) for b in boxes)
        ]
        text = "".join(c["c"] for c in chars).strip()
        if any(c.isalnum() for c in text):
            parts.append(
                {
                    "unit_id": unit["id"],
                    "page": unit["page"],
                    "quote": text,
                    "rects": char_rects(chars),
                    "method": "source",
                    "context": unit["text"],
                    "text_anchor": text_anchor(unit, text),
                }
            )
    return parts


def copied_projection(source: dict, target: dict, annotation: dict) -> list[dict]:
    """Copy only pages with identical text AND character positions, not page numbers alone."""
    page = annotation["pageIndex"]

    def signature(index, number):
        return [
            (normalized(c["c"]), c["b"])
            for u in index["units"]
            if u["page"] == number
            for c in u["chars"]
            if c["b"] and normalized(c["c"])
        ]

    before = signature(source, page)
    if not before:
        return []
    origin = source.get("origin_pages", [None] * len(source["pages"]))[page]
    result = []
    for number, size in enumerate(target["pages"]):
        if origin is not None and target.get("origin_pages", [None] * len(target["pages"]))[number] != origin:
            continue
        if size != source["pages"][page] or signature(target, number) != before:
            continue
        parts = selection_parts(target, {**annotation, "pageIndex": number})
        for part in parts:
            part["method"] = "copied-page"
            part.pop("context", None)
        result.extend(parts)
    return result


def snap_text_mark(index: dict, annotation: dict, *, oversized_only: bool = False) -> dict:
    """Fit text marks to their rows, preserving the submitted geometry for recovery.

    At the write boundary, only oversized font boxes need correction. Already
    precise client geometry must survive saving without shifting or widening.
    """
    ink = annotation.get("type") == 15 and annotation.get("intent") == "InkHighlight"
    if not ink and annotation.get("type") not in {9, 10, 11, 12}:
        return annotation
    lines = []
    for unit in index["units"]:
        if unit["page"] != annotation["pageIndex"]:
            continue
        for char in unit["chars"]:
            if not char["b"] or char["c"].isspace():
                continue
            bounds = fitz.Rect(char["b"])
            center = (bounds.y0 + bounds.y1) / 2
            line = next((line for line in lines if abs(line["center"] - center) < bounds.height * 0.3), None)
            if line is None:
                line = {"center": center, "chars": []}
                lines.append(line)
            line["chars"].append(char)
    boxes = annotation.get("segmentRects", []) or [annotation["rect"]]
    segments = []
    for segment in boxes:
        b = fitz.Rect(box(segment))
        eligible = [line for line in lines if any(b.x0 <= (c["b"][0] + c["b"][2]) / 2 <= b.x1 for c in line["chars"])]
        if not eligible:
            segments.append(segment)
            continue
        line = min(eligible, key=lambda line: abs(line["center"] - (b.y0 + b.y1) / 2))
        if abs(line["center"] - (b.y0 + b.y1) / 2) > max(8, min(b.height, 20)):
            segments.append(segment)
            continue
        chars = [c for c in line["chars"] if b.x0 <= (c["b"][0] + c["b"][2]) / 2 <= b.x1]
        # Geometry groups already represent a physical line; unit-local line numbers differ.
        band = union([rect(c["b"]) for c in chars])
        if oversized_only and not ink and b.height <= band["size"]["height"] * 1.35:
            segments.append(segment)
            continue
        # Raw extraction boxes include font ascent/descent padding. Keep the
        # repaired marker inside its line so it cannot capture the next line's clicks.
        padding = band["size"]["height"] * 0.1
        band["origin"]["y"] += padding
        band["size"]["height"] -= 2 * padding
        segments.append(band)
    if not segments or segments == boxes and not ink:
        return annotation
    result = {
        **annotation,
        "type": 9 if ink else annotation["type"],
        "rect": union(segments),
        "segmentRects": segments,
        "readerOriginalAppearance": annotation.get("readerOriginalAppearance", annotation),
    }
    if ink:
        result.pop("inkList", None)
        result.pop("intent", None)
        result["opacity"] = 0.4
    if result["type"] in {10, 11, 12}:
        result["strokeWidth"] = min(result.get("strokeWidth", 1), 1.5)
    return result


def locate_quote(unit: dict, quote: str) -> list[dict]:
    """Return geometry only for a unique exact normalized quote in a real unit."""
    needle = normalized(quote)
    haystack, offsets = "", []
    for i, char in enumerate(unit["chars"]):
        value = normalized(char["c"])
        haystack += value
        offsets.extend([i] * len(value))
    if not needle or haystack.count(needle) != 1:
        return []
    start = haystack.index(needle)
    return char_rects(unit["chars"][offsets[start] : offsets[start + len(needle) - 1] + 1])


def public_units(index: dict, pages: set[int] | None = None) -> list[dict]:
    return [
        {"id": u["id"], "page": u["page"], "text": u["text"]}
        for u in index["units"]
        if pages is None or u["page"] in pages
    ]


def recorded_mappings(source: dict, target: dict, records: list[dict]) -> list[dict]:
    """Recorded translator pairs establish paragraphs, not word-level equivalence."""
    mappings = []
    for record in records:
        src, dst = normalized(record["source"]), normalized(record["target"])
        if len(src) < 10 or len(dst) < 4 or re.search(r"\{v\d+\}", record["source"]):
            continue
        page = int(record["page"]) if record.get("page") is not None else None
        source_units = [
            u
            for u in source["units"]
            if (page is None or u["page"] == page) and len(normalized(u["text"])) >= 6 and normalized(u["text"]) in src
        ]
        page_map = target.get("origin_pages", list(range(len(target["pages"]))))
        target_units = [
            u
            for u in target["units"]
            if (page is None or page_map[u["page"]] == page)
            and len(normalized(u["text"])) >= 4
            and normalized(u["text"]) in dst
        ]
        # Repeated identical paragraphs are ambiguous. Leave them for explicit mapping.
        if len({u["page"] for u in source_units}) != 1 or len({u["page"] for u in target_units}) != 1:
            continue
        if source_units and target_units:
            mappings.append(
                {
                    "source_ids": [u["id"] for u in source_units],
                    "target_ids": [u["id"] for u in target_units],
                    "method": "translation-record",
                }
            )
    return mappings


def page_correspondence(source: dict, target: dict, kind: str) -> list[int | None]:
    if kind == "original":
        return list(range(len(target["pages"])))
    if kind != "bilingual" and len(source["pages"]) == len(target["pages"]):
        # These artifacts are produced by pdf2zh, which replaces content within existing pages.
        return list(range(len(target["pages"])))
    result = [None] * len(target["pages"])
    if kind == "bilingual" and len(target["pages"]) == 2 * len(source["pages"]):
        for page in range(len(source["pages"])):
            original = normalized(" ".join(u["text"] for u in source["units"] if u["page"] == page))
            copied = normalized(" ".join(u["text"] for u in target["units"] if u["page"] == 2 * page))
            if original and original == copied:
                result[2 * page : 2 * page + 2] = [page, page]
    return result


def figure_projection(source: dict, target: dict, annotation: dict) -> list[dict]:
    bounds = fitz.Rect(box(annotation["rect"]))
    parents = [
        f
        for f in source.get("figures", [])
        if f["page"] == annotation["pageIndex"] and fitz.Rect(box(f["rect"])).contains(bounds)
    ]
    if len(parents) != 1:
        return []
    original = parents[0]
    candidates = [f for f in target.get("figures", []) if f["digest"] == original["digest"]]
    # Identical repeated logos/images are not reliable content anchors.
    page_map = source.get("origin_pages", [])
    origin_page = page_map[annotation["pageIndex"]] if page_map else None
    if origin_page is not None:
        candidates = [
            f for f in candidates if target.get("origin_pages", [None] * len(target["pages"]))[f["page"]] == origin_page
        ]
    if not candidates or len({f["page"] for f in candidates}) != len(candidates):
        return []
    result = []
    for figure in candidates:
        # Equal pixel digests do not imply equal orientation (e.g. a rotated square plot).
        before_matrix, after_matrix = original.get("transform"), figure.get("transform")
        if before_matrix and after_matrix:
            before_scale = sum(n * n for n in before_matrix[:4]) ** 0.5
            after_scale = sum(n * n for n in after_matrix[:4]) ** 0.5
            if (
                not before_scale
                or not after_scale
                or any(
                    abs(a / before_scale - b / after_scale) > 0.01
                    for a, b in zip(before_matrix[:4], after_matrix[:4], strict=True)
                )
            ):
                continue
        before, after = original["rect"], figure["rect"]
        sx, sy = after["size"]["width"] / before["size"]["width"], after["size"]["height"] / before["size"]["height"]
        if abs(sx - sy) > max(sx, sy) * 0.02:
            continue

        def transform(value, before=before, after=after, sx=sx, sy=sy):
            if isinstance(value, dict):
                if set(value) == {"x", "y"}:
                    return {
                        "x": after["origin"]["x"] + (value["x"] - before["origin"]["x"]) * sx,
                        "y": after["origin"]["y"] + (value["y"] - before["origin"]["y"]) * sy,
                    }
                if set(value) == {"width", "height"}:
                    return {"width": value["width"] * sx, "height": value["height"] * sy}
                return {k: transform(v) for k, v in value.items()}
            if isinstance(value, list):
                return [transform(v) for v in value]
            return value

        geometry = {
            k: transform(v)
            for k, v in annotation.items()
            if k in {"rect", "inkList", "vertices", "linePoints", "segmentRects", "unrotatedRect"}
        }
        result.append(
            {
                "page": figure["page"],
                "unit_id": f"figure:{figure['digest']}",
                "quote": "图像内容一致",
                "rects": [geometry["rect"]],
                "geometry": geometry,
                "method": "figure",
            }
        )
    return result
