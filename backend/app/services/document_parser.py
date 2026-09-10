"""Loss-aware PDF reading blocks. The original PDF remains the source of truth."""

from __future__ import annotations

import hashlib
import re
from collections import Counter

import fitz

SCHEMA_VERSION = 1
HEADING = re.compile(
    r"^(?:\d+(?:\.\d+)*\.?\s+\S|abstract\b|introduction\b|conclusions?\b|references\b|acknowledg|appendix\b)", re.I
)
CAPTION = re.compile(r"^(?:fig(?:ure)?\.?|table)\s*\d+", re.I)


def clean_text(text: str) -> str:
    text = re.sub(r"(?<=[a-zA-Z])-\n(?=[a-z])", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _ordered(items: list[dict], width: float) -> list[dict]:
    """Read narrow columns within bands delimited by spanning blocks."""
    items = sorted(items, key=lambda b: (b["bbox"][1], b["bbox"][0]))
    middle = width / 2
    left = [b for b in items if b["bbox"][2] < middle + 15 and b["bbox"][2] - b["bbox"][0] > width * 0.2]
    right = [b for b in items if b["bbox"][0] > middle - 15 and b["bbox"][2] - b["bbox"][0] > width * 0.2]
    if len(left) < 2 or len(right) < 2:
        return items
    spans = [b for b in items if b["bbox"][0] < middle - 20 and b["bbox"][2] > middle + 20]
    rest = [b for b in items if b not in spans]
    ordered: list[dict] = []
    for span in [*spans, None]:
        stop = span["bbox"][1] if span else float("inf")
        band = [b for b in rest if b["bbox"][1] < stop]
        rest = [b for b in rest if b["bbox"][1] >= stop]
        for column in (0, 1):
            ordered.extend(
                sorted([b for b in band if int(b["bbox"][0] >= middle - 15) == column], key=lambda b: b["bbox"][1])
            )
        if span:
            ordered.append(span)
    return ordered


def parse_document(pdf_bytes: bytes, filename: str = "Paper.pdf") -> dict:
    digest = hashlib.sha256(pdf_bytes).hexdigest()[:12]
    blocks: list[dict] = []
    pages = []
    warnings = []
    with fitz.open(stream=pdf_bytes, filetype="pdf") as pdf:
        if pdf.is_encrypted:
            raise ValueError("PDF 已加密，请上传解除密码保护的版本。")
        title = (pdf.metadata or {}).get("title") or filename.removesuffix(".pdf")
        for page_index, page in enumerate(pdf):
            width, height = page.cropbox.width, page.cropbox.height
            pages.append({"page": page_index + 1, "width": width, "height": height})
            items = []
            table_rects = []
            try:
                for table in page.find_tables().tables:
                    rows = table.extract()
                    if len(rows) < 2:
                        continue
                    text = "\n".join(" | ".join(str(c or "") for c in row) for row in rows)
                    table_rects.append(fitz.Rect(table.bbox))
                    items.append({"type": "table", "source_text": text, "bbox": list(table.bbox), "rows": rows})
            except Exception:
                warnings.append(f"第 {page_index + 1} 页表格结构无法可靠提取，请核对原页。")
            text_dict = page.get_text("dict", flags=fitz.TEXTFLAGS_DICT & ~fitz.TEXT_PRESERVE_IMAGES)
            sizes = Counter()
            for raw in text_dict["blocks"]:
                if raw.get("type") != 0:
                    continue
                lines = raw.get("lines", [])
                spans = [s for line in lines for s in line["spans"]]
                text = clean_text("\n".join("".join(s["text"] for s in line["spans"]) for line in lines))
                if not text:
                    continue
                rect = fitz.Rect(raw["bbox"])
                if any(t.contains(rect) for t in table_rects):
                    continue
                for s in spans:
                    sizes[round(s["size"])] += len(s["text"])
                size = max((s["size"] for s in spans), default=10)
                symbols = len(re.findall(r"[=∑∏∫∂∇≤≥±∞∈]", text))
                kind = "equation" if symbols and len(text) < 260 and len(text.split()) < 40 else "paragraph"
                if CAPTION.match(text):
                    kind = "caption"
                items.append({"type": kind, "source_text": text, "bbox": list(rect), "font_size": size})
            body_size = sizes.most_common(1)[0][0] if sizes else 10
            for item in items:
                t = item["source_text"]
                if (
                    item["type"] == "paragraph"
                    and len(t) < 160
                    and (HEADING.match(t) or item.get("font_size", 0) > body_size * 1.22)
                ):
                    item["type"] = "heading"
            graphics = [fitz.Rect(info["bbox"]) for info in page.get_image_info()]
            try:
                graphics.extend(page.cluster_drawings())
            except (AttributeError, ValueError):
                pass
            regions: list[fitz.Rect] = []
            for rect in graphics:
                rect = fitz.Rect(rect)
                if rect.width < 55 or rect.height < 40 or any(t.intersects(rect) for t in table_rects):
                    continue
                if any(r.contains(rect) for r in regions):
                    continue
                regions = [r for r in regions if not rect.contains(r)]
                regions.append(rect)
            for rect in regions:
                captions = [
                    i
                    for i in items
                    if i["type"] == "caption"
                    and abs(i["bbox"][1] - rect.y1) < 95
                    and i["bbox"][0] < rect.x1
                    and i["bbox"][2] > rect.x0
                ]
                caption = min(captions, key=lambda b: abs(b["bbox"][1] - rect.y1), default=None)
                items.append(
                    {"type": "figure", "source_text": caption["source_text"] if caption else "", "bbox": list(rect)}
                )
            if not any(i["source_text"] for i in items):
                items = [{"type": "scan", "source_text": "", "bbox": [0, 0, width, height]}]
                warnings.append(f"第 {page_index + 1} 页没有可提取文本，显示原始页面，可请求图像解读。")
            for item in _ordered(items, width):
                stable = hashlib.sha256(
                    f'{digest}:{page_index}:{item["type"]}:{item["bbox"]}:{item["source_text"]}'.encode()
                ).hexdigest()[:16]
                item.update(id=f"b_{stable}", page=page_index + 1, index=len(blocks))
                item.pop("font_size", None)
                item["sentences"] = [
                    {"id": f"b_{stable}_s{n}", "text": m.group(), "start": m.start(), "end": m.end()}
                    for n, m in enumerate(re.finditer(r"[^.!?。！？]+[.!?。！？]*", item["source_text"]))
                    if m.group().strip()
                ]
                blocks.append(item)
    sections = []
    current = "section-start"
    for block in blocks:
        if block["type"] == "heading":
            current = f'section-{block["id"]}'
            sections.append(
                {"id": current, "title": block["source_text"], "block_id": block["id"], "page": block["page"]}
            )
        elif not sections:
            sections.append({"id": current, "title": "论文开篇", "block_id": block["id"], "page": block["page"]})
        block["section_id"] = current
    return {
        "schema_version": SCHEMA_VERSION,
        "fingerprint": digest,
        "title": title,
        "page_count": len(pages),
        "pages": pages,
        "sections": sections,
        "blocks": blocks,
        "warnings": warnings,
    }


def render_source(pdf_path: str, block: dict, full_page: bool = False) -> bytes:
    with fitz.open(pdf_path) as pdf:
        page = pdf[block["page"] - 1]
        page.set_rotation(0)
        clip = page.rect if full_page else (fitz.Rect(block["bbox"]) + (-6, -6, 6, 6)) & page.rect
        return page.get_pixmap(matrix=fitz.Matrix(1.6, 1.6), clip=clip, alpha=False).tobytes("png")


def evidence_for(block: dict) -> dict:
    return {"block_id": block["id"], "page": block["page"], "quote": block["source_text"], "bbox": block["bbox"]}


def tagged_text(blocks: list[dict]) -> str:
    return "\n\n".join(f'[{b["id"]}, page {b["page"]}] {b["source_text"]}' for b in blocks if b["source_text"])


def validate_evidence(data: object, blocks: list[dict]) -> object:
    """Never accept model-invented page numbers, quotations or unknown anchors."""
    lookup = {b["id"]: b for b in blocks}

    def visit(value):
        if isinstance(value, dict):
            result = {k: visit(v) for k, v in value.items() if k != "evidence_refs"}
            if "evidence_refs" in value:
                refs = value["evidence_refs"] if isinstance(value["evidence_refs"], list) else []
                ids = [r if isinstance(r, str) else r.get("block_id") if isinstance(r, dict) else None for r in refs]
                result["evidence_refs"] = [evidence_for(lookup[key]) for key in dict.fromkeys(ids) if key in lookup]
            return result
        if isinstance(value, list):
            return [visit(v) for v in value]
        return value

    return visit(data)
