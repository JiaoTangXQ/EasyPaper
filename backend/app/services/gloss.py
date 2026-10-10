"""Prepare a complete click-to-gloss layer over original paper text."""

from __future__ import annotations

import hashlib
import json
import re

from .reader_geometry import normalized

LABELS = {
    "word": "单词",
    "term": "多词术语",
    "collocation": "固定搭配",
    "idiom": "俚语",
    "discourse": "逻辑连接",
    "pattern": "学术句式",
    "abbreviation": "缩写",
}

GLOSS_SYSTEM = (
    "你在为英文学术论文做点读准备。每个句子都要切成前后相接、互不重叠的块，并铺满整句。"
    "读者点到块里的任意一个词，都会看到这一整块的解释，所以固定搭配、俚语、术语、句式和缩写必须整块切出。\n"
    "类别只能是 word、term、collocation、idiom、discourse、pattern、abbreviation。\n"
    "word 是单独一个单词，给出 zh（中文意思）和 en（一句简短英文释义）。\n"
    "其余类别给出 zh（中文意思）和 role（它在这句里起什么作用），不要给 en。\n"
    "标点附在相邻块上。text 必须按顺序抄自原句，合起来覆盖每一个词。\n"
    '只返回 JSON：{"sentences":[{"id":"原句 id","spans":[{"text":"...","category":"word","zh":"...","en":"..."}]}]}'
)


class GlossCoverageError(ValueError):
    pass


def tile_sentence(source: str, spans: list, unit: dict | None = None, units: list | None = None) -> list[dict]:
    """Partition one sentence. Every non-space character belongs to exactly one span."""
    if not isinstance(spans, list) or not spans:
        raise GlossCoverageError("没有切块")
    cursor = 0
    produced = []
    for raw in spans:
        if not isinstance(raw, dict) or not isinstance(raw.get("text"), str) or not normalized(raw["text"]):
            raise GlossCoverageError("切块没有可用的原文")
        begin, end = _consume(source, cursor, raw["text"])
        produced.append(_present(source[begin:end].strip(), raw, begin, end, unit, units))
        cursor = end
    if normalized(source[cursor:]):
        raise GlossCoverageError("句子还有没覆盖的内容")
    return produced


async def prepare_gloss(ai, units: list[dict]) -> list[dict]:
    """Ask the model to cover every sentence, retrying a sentence once if its tiling fails."""
    ready = []
    for batch in _batches(units):
        try:
            ready.extend(await _cover(ai, batch, units))
        except GlossCoverageError:
            for unit in batch:
                try:
                    ready.extend(await _cover(ai, [unit], units))
                except GlossCoverageError:
                    ready.extend(await _cover(ai, [unit], units))
    return ready


def _batches(units: list[dict]) -> list[list[dict]]:
    batches, current, size = [], [], 0
    for unit in units:
        text = unit.get("text") or ""
        if not normalized(text):
            continue
        if current and (len(current) >= 6 or size + len(text) > 3500):
            batches.append(current)
            current, size = [], 0
        current.append(unit)
        size += len(text)
    if current:
        batches.append(current)
    return batches


async def _cover(ai, batch: list[dict], units: list[dict]) -> list[dict]:
    user = json.dumps(
        {"sentences": [{"id": unit["id"], "text": unit["text"]} for unit in batch]},
        ensure_ascii=False,
    )
    result = await ai.complete_json(GLOSS_SYSTEM, user, max_tokens=8192)
    sentences = result.get("sentences") if isinstance(result, dict) else None
    if not isinstance(sentences, list):
        raise GlossCoverageError("返回里没有句子")
    by_id = {}
    for item in sentences:
        if isinstance(item, dict) and isinstance(item.get("id"), str):
            by_id[item["id"]] = item
    if set(by_id) != {unit["id"] for unit in batch}:
        raise GlossCoverageError("返回的句子和原文对不上")
    covered = []
    for unit in batch:
        covered.extend(tile_sentence(unit["text"], by_id[unit["id"]].get("spans") or [], unit, units))
    return covered


def _consume(source: str, start: int, piece: str) -> tuple[int, int]:
    target = normalized(piece)
    index = start
    while index < len(source) and not normalized(source[index]):
        index += 1
    begin = index
    matched = ""
    while matched != target:
        if index >= len(source):
            raise GlossCoverageError("切块对不上原文")
        index += 1
        matched = normalized(source[begin:index])
        if len(matched) > len(target):
            raise GlossCoverageError("切块对不上原文")
    return begin, index


def _present(text: str, raw: dict, begin: int, end: int, unit: dict | None, units: list | None) -> dict:
    category = raw.get("category")
    if category not in LABELS:
        raise GlossCoverageError("有无法归类的块")
    zh = raw.get("zh")
    if not isinstance(zh, str) or not zh.strip():
        raise GlossCoverageError("块缺少中文解释")
    if category == "word":
        if len(re.findall(r"[A-Za-z0-9]+(?:[-'’][A-Za-z0-9]+)*", text)) > 1:
            raise GlossCoverageError("单词块里有多个词")
        en = raw.get("en")
        if not isinstance(en, str) or not en.strip():
            raise GlossCoverageError("单词缺少英文释义")
        extra = {"en": en.strip()}
    else:
        role = raw.get("role")
        if not isinstance(role, str) or not role.strip():
            raise GlossCoverageError("块缺少它在句中的作用")
        extra = {"role": role.strip()}
    span = {
        "id": hashlib.sha256(f"{unit['id'] if unit else text}:{begin}:{text}".encode()).hexdigest()[:16],
        "text": text,
        "category": category,
        "label": LABELS[category],
        "zh": zh.strip(),
        **extra,
    }
    if unit is not None:
        span["page"] = unit["page"]
        span["anchor"] = _anchor(unit, begin, end, units or [])
    return span


def _anchor(unit: dict, begin: int, end: int, units: list) -> dict:
    before = normalized(unit["text"][:begin])
    after = normalized(unit["text"][end:])
    page_units = [item for item in units if item.get("page") == unit["page"]]
    position = next((index for index, item in enumerate(page_units) if item.get("id") == unit["id"]), None)
    if position is not None:
        before = "".join(normalized(item["text"]) for item in page_units[:position]) + before
        after += "".join(normalized(item["text"]) for item in page_units[position + 1 :])
    return {
        "text": unit["text"][begin:end].strip(),
        "prefix": before[-48:],
        "suffix": after[:48],
        "schema": 3,
    }
