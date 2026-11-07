"""Prepare a complete click-to-gloss layer over original paper text."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import re

from .ai_client import AIError
from .reader_geometry import normalized

# Keep each request below the model's timeout while amortizing Cursor startup
# and network latency across more sentences. Coverage validation still splits
# an individual batch when the model cannot return a complete tiling.
# Tiling asks for word-level spans, merging only fixed phrases and multi-word terms.
GLOSS_MODEL = "grok-4.7-low-fast"
GLOSS_BATCH_UNITS = 24
GLOSS_BATCH_CHARS = 1800
GLOSS_LONG_SENTENCE_CHARS = 450
GLOSS_CALL_TIMEOUT = 180
GLOSS_CONCURRENCY = 2

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
    "读者点到块内任意字符都会看到该块的释义，因此多词术语、固定搭配等必须把对应词连续写在同一块的 text 里。\n"
    "颗粒度（必须遵守）：\n"
    "1. 独立词：每个在句中可单独理解的英文词（含 a/the/is/and 等功能词）默认单独成块，用 category=word，给出 zh、ipa，以及 en 与 simple_en（CEFR B1-B2 常用词写的简短英文解释）。\n"
    "2. 固定搭配：仅当 2–6 个词必须连在一起理解（如 depend on、in contrast、as well as）时合并为 category=collocation；"
    "role 用中文说明它和句中哪几个词绑定（例如「与后面的 on … 连用」），不要写成整句翻译。\n"
    "3. 多词术语/名词短语：论文里的专有名词、方法名、实体名等若由多个词组成（如 reinforcement learning、state transition model），"
    "整个短语用 category=term 单独成块；点到短语里任意一个词都应显示整段 term 的 zh。\n"
    "4. idiom、discourse（如 however / therefore）、pattern（仅 2–5 词的学术套路，如 we show that，不要整段从句）、abbreviation 按语义整块切出。\n"
    "禁止：把半句、整句、长从句或「前面一大段」并成一个块；禁止为了省事少切块；禁止用 pattern 或 term 包裹整句做整句翻译。\n"
    "类别只能是 word、term、collocation、idiom、discourse、pattern、abbreviation。"
    "每个块都必须有 simple_en；除 word 外给出 zh 与 role（或缩写说明）。"
    "标点附在相邻块上。text 必须按顺序抄自原句，合起来覆盖每一个词。\n"
    '只返回 JSON：{"sentences":[{"id":"原句 id","spans":[{"text":"...","category":"word","zh":"...","ipa":"...","en":"...","simple_en":"..."}]}]}'
)

_SIMPLE_EN_FALLBACKS = {
    "term": "This term names an idea or thing in the text.",
    "collocation": "These words are often used together.",
    "idiom": "This expression has a meaning beyond the individual words.",
    "discourse": "This phrase connects this idea to the next one.",
    "pattern": "This sentence pattern shows the idea in the sentence.",
    "abbreviation": "This short form stands for a longer term.",
}


class GlossCoverageError(ValueError):
    pass


def tile_sentence(
    source: str,
    spans: list,
    unit: dict | None = None,
    units: list | None = None,
    page_units_by_page: dict | None = None,
) -> list[dict]:
    """Partition one sentence. Every non-space character belongs to exactly one span."""
    if not isinstance(spans, list) or not spans:
        raise GlossCoverageError("没有切块")
    if page_units_by_page is None and unit is not None and units is not None:
        page_units_by_page = _group_page_units(units)
    cursor = 0
    produced = []
    for raw in spans:
        if not isinstance(raw, dict) or not isinstance(raw.get("text"), str) or not normalized(raw["text"]):
            raise GlossCoverageError("切块没有可用的原文")
        begin, end = _consume(source, cursor, raw["text"])
        produced.append(
            _present(source[begin:end].strip(), raw, begin, end, unit, page_units_by_page)
        )
        cursor = end
    if normalized(source[cursor:]):
        raise GlossCoverageError("句子还有没覆盖的内容")
    return produced


async def prepare_gloss(
    ai, units: list[dict], on_progress=None, on_batch=None, skip_ids=None, concurrency: int = 1
) -> list[dict]:
    """Cover every sentence. A timed-out batch is split; a bad tiling is retried once."""
    skip = set(skip_ids or ())
    batches = [batch for batch in _batches(units) if any(unit.get("id") not in skip for unit in batch)]
    page_units_by_page = _group_page_units(units)
    total = len(batches)
    if concurrency <= 1:
        ready = []
        for index, batch in enumerate(batches, start=1):
            produced = await _finish_batch(ai, batch, units, skip, page_units_by_page)
            ready.extend(produced)
            if produced and on_batch:
                await _notify(on_batch, produced)
            if on_progress:
                await _notify(on_progress, index, total)
        return ready

    slots = asyncio.Semaphore(concurrency)
    lock = asyncio.Lock()
    finished = 0

    async def run(batch):
        nonlocal finished
        async with slots:
            try:
                produced = await _finish_batch(ai, batch, units, skip, page_units_by_page)
            except Exception as exc:
                return exc
        async with lock:
            if produced and on_batch:
                await _notify(on_batch, produced)
            nonlocal_finished = finished + 1
            finished = nonlocal_finished
            if on_progress:
                await _notify(on_progress, finished, total)
        return produced

    outcomes = await asyncio.gather(*(run(batch) for batch in batches))
    failed = next((item for item in outcomes if isinstance(item, Exception)), None)
    ready = [span for item in outcomes if isinstance(item, list) for span in item]
    if failed:
        raise failed
    return ready


async def _notify(callback, *args):
    """Run sync callbacks inline and let persistence callbacks yield to the loop."""
    result = callback(*args)
    if inspect.isawaitable(result):
        await result


async def _finish_batch(ai, batch, units, skip, page_units_by_page) -> list[dict]:
    pending = [unit for unit in batch if unit.get("id") not in skip]
    if not pending:
        return []
    return await _cover_batch(ai, pending, units, page_units_by_page)


async def _cover_batch(ai, batch: list[dict], units: list[dict], page_units_by_page: dict) -> list[dict]:
    try:
        return await _cover(ai, batch, units, page_units_by_page)
    except GlossCoverageError:
        if len(batch) == 1:
            try:
                return await _cover(ai, batch, units, page_units_by_page)
            except GlossCoverageError:
                return await _fallback_unit(ai, batch[0], units, page_units_by_page)
        covered = []
        for unit in batch:
            covered.extend(await _cover_batch(ai, [unit], units, page_units_by_page))
        return covered
    except AIError:
        if len(batch) == 1:
            return await _cover(ai, batch, units, page_units_by_page)
        middle = len(batch) // 2
        return await _cover_batch(ai, batch[:middle], units, page_units_by_page) + await _cover_batch(
            ai, batch[middle:], units, page_units_by_page
        )


def _batches(units: list[dict]) -> list[list[dict]]:
    batches, current, size = [], [], 0
    for unit in units:
        text = unit.get("text") or ""
        if not normalized(text):
            continue
        # Keep an unusually long sentence isolated. It already consumes most
        # of the request budget, and mixing another sentence with it makes
        # malformed tilings more likely without improving throughput.
        if current and (
            len(current) >= GLOSS_BATCH_UNITS
            or size + len(text) > GLOSS_BATCH_CHARS
            or len(text) > GLOSS_LONG_SENTENCE_CHARS
        ):
            batches.append(current)
            current, size = [], 0
        current.append(unit)
        size += len(text)
        if len(text) > GLOSS_LONG_SENTENCE_CHARS:
            batches.append(current)
            current, size = [], 0
    if current:
        batches.append(current)
    return batches


async def _cover(ai, batch: list[dict], units: list[dict], page_units_by_page: dict) -> list[dict]:
    user = json.dumps(
        {"sentences": [{"id": unit["id"], "text": unit["text"]} for unit in batch]},
        ensure_ascii=False,
    )
    result = await ai.complete_json(
        GLOSS_SYSTEM,
        user,
        max_tokens=8192,
        timeout_seconds=GLOSS_CALL_TIMEOUT,
        model=GLOSS_MODEL,
        bypass_slot=True,
    )
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
        raw_spans = by_id[unit["id"]].get("spans") or []
        _reject_overmerged_tiling(unit["text"], raw_spans)
        covered.extend(
            tile_sentence(
                unit["text"],
                raw_spans,
                unit,
                units,
                page_units_by_page,
            )
        )
    return covered


def _reject_overmerged_tiling(source: str, spans: list) -> None:
    """Push the model away from whole-sentence gloss tiles."""
    if not isinstance(spans, list) or not spans:
        return
    words = _words(source)
    if len(words) < 8:
        return
    if len(spans) == 1:
        raise GlossCoverageError("句子被合并成一块")
    if len(spans) <= 3 and len(words) >= 12:
        covered = sum(len(_words(item.get("text") or "")) for item in spans if isinstance(item, dict))
        if covered >= max(len(words) - 2, int(len(words) * 0.85)):
            raise GlossCoverageError("切块过粗")


async def _fallback_unit(ai, unit: dict, units: list[dict], page_units_by_page: dict) -> list[dict]:
    """Keep the sentence clickable when the model cannot tile it."""
    zh = ""
    try:
        result = await ai.complete_json(
            "把英文原文译成一句简体中文，保留术语和缩写。只返回 JSON：{\"zh\":\"中文\"}。",
            json.dumps({"text": unit["text"]}, ensure_ascii=False),
            max_tokens=512,
            timeout_seconds=60,
            model=GLOSS_MODEL,
            bypass_slot=True,
        )
        if isinstance(result, dict) and isinstance(result.get("zh"), str):
            zh = result["zh"].strip()
    except AIError:
        zh = ""
    if not zh:
        zh = "这句按整句理解"
    return tile_sentence(
        unit["text"],
        [{"text": unit["text"], "category": "pattern", "zh": zh, "role": "整句理解"}],
        unit,
        units,
        page_units_by_page,
    )


def _words(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9]+(?:[-'’][A-Za-z0-9]+)*", text)


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


def _present(
    text: str,
    raw: dict,
    begin: int,
    end: int,
    unit: dict | None,
    page_units_by_page: dict | None,
) -> dict:
    category = raw.get("category")
    if category not in LABELS:
        category = "term"
    zh = raw.get("zh")
    if not isinstance(zh, str) or not zh.strip():
        raise GlossCoverageError("块缺少中文解释")
    if category == "word" and len(_words(text)) > 1:
        # A phrase mislabeled as one word is still a useful click target.
        category = "term"
    if category == "word":
        en = raw.get("en")
        if not isinstance(en, str) or not en.strip():
            en = raw.get("simple_en")
        fallback = not isinstance(en, str) or not en.strip()
        if not isinstance(en, str) or not en.strip():
            en = "见中文释义"
        extra = {"en": en.strip(), "simple_en": "See the Chinese meaning." if fallback else en.strip()}
    else:
        role = raw.get("role")
        if not isinstance(role, str) or not role.strip():
            role = "这几个词作为一个整体"
        extra = {"role": role.strip()}
        simple_en = raw.get("simple_en") or raw.get("en")
        if isinstance(simple_en, str) and simple_en.strip():
            extra["simple_en"] = simple_en.strip()
        else:
            # Keep newly generated bundles complete if a provider omits the
            # required field. This avoids a click-time enrichment request.
            extra["simple_en"] = _SIMPLE_EN_FALLBACKS.get(
                category,
                "This group of words works together as one meaning.",
            )
    ipa = raw.get("ipa")
    if isinstance(ipa, str) and ipa.strip():
        extra["ipa"] = ipa.strip().strip("/")
    span = {
        "id": hashlib.sha256(f"{unit['id'] if unit else text}:{begin}:{text}".encode()).hexdigest()[:16],
        "unit_id": unit["id"] if unit else "",
        "text": text,
        "category": category,
        "label": LABELS[category],
        "zh": zh.strip(),
        **extra,
    }
    if unit is not None:
        span["page"] = unit["page"]
        span["anchor"] = _anchor(unit, begin, end, page_units_by_page or {})
    return span


def _anchor(unit: dict, begin: int, end: int, page_units_by_page: dict) -> dict:
    before = normalized(unit["text"][:begin])
    after = normalized(unit["text"][end:])
    page_context = page_units_by_page.get(unit.get("page"))
    if isinstance(page_context, dict):
        # _group_page_units precomputes the page-wide context once. This keeps
        # anchor creation linear in the number of spans instead of rescanning
        # every preceding/following sentence for each span.
        context = page_context.get(unit.get("id"))
        if context is not None:
            before = context[0] + before
            after += context[1]
    elif page_context is not None:
        # Accept the old list shape for callers that construct the map
        # themselves (and for compatibility with persisted/legacy tooling).
        position = next((index for index, item in enumerate(page_context) if item.get("id") == unit["id"]), None)
        if position is not None:
            before = "".join(normalized(item["text"]) for item in page_context[:position]) + before
            after += "".join(normalized(item["text"]) for item in page_context[position + 1 :])
    return {
        "text": unit["text"][begin:end].strip(),
        "prefix": before[-48:],
        "suffix": after[:48],
        "schema": 3,
    }


def _group_page_units(units: list[dict]) -> dict:
    grouped = {}
    for unit in units:
        grouped.setdefault(unit.get("page"), []).append(unit)
    contexts = {}
    for page, page_units in grouped.items():
        before = ""
        prefixes = {}
        for unit in page_units:
            unit_id = unit.get("id")
            if unit_id:
                prefixes[unit_id] = before
            before += normalized(unit.get("text") or "")
        after = ""
        suffixes = {}
        for unit in reversed(page_units):
            unit_id = unit.get("id")
            if unit_id:
                suffixes[unit_id] = after
            after = normalized(unit.get("text") or "") + after
        contexts[page] = {unit_id: (prefixes[unit_id], suffixes[unit_id]) for unit_id in prefixes}
    return contexts
