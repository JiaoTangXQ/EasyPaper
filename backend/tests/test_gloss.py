import json

import pytest

from app.services.ai_client import AIError
from app.services.gloss import GlossCoverageError, _batches, prepare_gloss, tile_sentence


def test_gloss_batches_keep_long_documents_within_a_bounded_request_count():
    units = [
        {
            "id": f"s{index}",
            "page": index // 40,
            "text": "The model stores energy in every cell and improves the result for the next experiment.",
        }
        for index in range(1000)
    ]

    batches = _batches(units)

    assert len(batches) <= 100


def test_tiles_a_sentence_into_a_pattern_and_keeps_the_original_words():
    source = "We show that the model outperforms the baseline."
    spans = tile_sentence(
        source,
        [
            {"text": "We show that", "category": "pattern", "zh": "我们证明", "role": "引出本文结论"},
            {"text": "the model", "category": "term", "zh": "该模型", "role": "指被比较的系统"},
            {"text": "outperforms", "category": "word", "zh": "优于", "en": "performs better than"},
            {"text": "the baseline.", "category": "term", "zh": "基线", "role": "用来比较的参照"},
        ],
    )
    assert [span["text"] for span in spans] == ["We show that", "the model", "outperforms", "the baseline."]
    assert spans[0]["label"] == "学术句式"
    assert spans[0]["role"] == "引出本文结论"
    assert "en" not in spans[0]
    assert spans[2]["label"] == "单词"
    assert spans[2]["en"] == "performs better than"
    assert "role" not in spans[2]


def test_rejects_a_gap_and_keeps_a_multiword_word_span_as_a_term():
    source = "The model learns quickly."
    with pytest.raises(GlossCoverageError):
        tile_sentence(source, [{"text": "The model", "category": "term", "zh": "该模型", "role": "研究对象"}])
    spans = tile_sentence(
        source,
        [{"text": "The model learns quickly.", "category": "word", "zh": "整句", "en": "the whole sentence"}],
    )
    assert spans[0]["category"] == "term"
    assert spans[0]["label"] == "多词术语"
    assert spans[0]["role"] == "这几个词作为一个整体"
    assert "en" not in spans[0]


def test_missing_gloss_fields_still_cover_the_sentence():
    word = tile_sentence("Energy.", [{"text": "Energy.", "category": "word", "zh": "能量"}])
    assert word[0]["en"] == "见中文释义"
    phrase = tile_sentence("at all.", [{"text": "at all.", "category": "collocation", "zh": "完全"}])
    assert phrase[0]["role"] == "这几个词作为一个整体"
    unknown = tile_sentence("Energy.", [{"text": "Energy.", "category": "noun", "zh": "能量", "role": "被讨论的对象"}])
    assert unknown[0]["category"] == "term"


@pytest.mark.asyncio
async def test_prepare_gloss_keeps_a_sentence_the_model_cannot_tile():
    units = [{"id": "s1", "page": 0, "text": "Energy is stored."}]
    gap = {
        "sentences": [
            {"id": "s1", "spans": [{"text": "Energy", "category": "word", "zh": "能量", "en": "power"}]}
        ]
    }
    ai = _AI([gap, gap, {"zh": "能量被储存。"}])
    spans = await prepare_gloss(ai, units)
    assert ai.calls == 3
    assert spans[0]["text"] == "Energy is stored."
    assert spans[0]["zh"] == "能量被储存。"
    assert spans[0]["category"] == "pattern"


def test_anchor_distinguishes_a_repeated_word():
    unit = {"id": "s1", "page": 0, "text": "The model is fixed. The budget is fixed."}
    spans = tile_sentence(
        unit["text"],
        [
            {"text": "The model", "category": "term", "zh": "该模型", "role": "被讨论的系统"},
            {"text": "is fixed.", "category": "collocation", "zh": "是固定的", "role": "说明模型不再更新"},
            {"text": "The budget", "category": "term", "zh": "预算", "role": "另一项被固定的对象"},
            {"text": "is fixed.", "category": "collocation", "zh": "是固定的", "role": "说明预算不再变化"},
        ],
        unit=unit,
        units=[unit],
    )
    assert spans[1]["anchor"]["prefix"] != spans[3]["anchor"]["prefix"]
    assert spans[1]["anchor"]["text"] == "is fixed."
    assert spans[3]["page"] == 0


def test_anchor_keeps_context_from_other_units_on_the_same_page():
    first = {"id": "s1", "page": 0, "text": "The first sentence."}
    second = {"id": "s2", "page": 0, "text": "The second sentence."}
    spans = tile_sentence(
        second["text"],
        [{"text": second["text"], "category": "pattern", "zh": "第二句", "role": "整句"}],
        unit=second,
        units=[first, second],
    )
    assert spans[0]["anchor"]["prefix"].endswith("thefirstsentence.")


@pytest.mark.asyncio
async def test_prepare_gloss_awaits_async_checkpoint_callbacks():
    seen = []

    async def checkpoint(produced):
        seen.extend(produced)

    spans = await prepare_gloss(_AI(["echo"]), [{"id": "s1", "page": 0, "text": "Energy is stored."}], on_batch=checkpoint)
    assert seen == spans


class _AI:
    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = 0

    async def complete_json(self, system, user, **kwargs):
        self.calls += 1
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        if answer == "echo":
            payload = json.loads(user)
            return {
                "sentences": [
                    {
                        "id": sentence["id"],
                        "spans": [
                            {
                                "text": sentence["text"],
                                "category": "pattern",
                                "zh": "整句意思",
                                "role": "陈述这一句",
                            }
                        ],
                    }
                    for sentence in payload["sentences"]
                ]
            }
        return answer


@pytest.mark.asyncio
async def test_prepare_gloss_retries_a_sentence_that_does_not_cover_the_source():
    units = [{"id": "s1", "page": 2, "text": "LLM means large language model."}]
    ai = _AI(
        [
            {
                "sentences": [
                    {
                        "id": "s1",
                        "spans": [{"text": "LLM", "category": "abbreviation", "zh": "大语言模型", "role": "本句被定义的缩写"}],
                    }
                ]
            },
            "echo",
        ]
    )
    spans = await prepare_gloss(ai, units)
    assert ai.calls == 2
    assert spans[0]["text"] == "LLM means large language model."
    assert spans[0]["category"] == "pattern"
    assert spans[0]["page"] == 2


@pytest.mark.asyncio
async def test_prepare_gloss_reports_each_finished_batch():
    units = [
        {"id": "s1", "page": 0, "text": "Energy is stored."},
        {"id": "s2", "page": 0, "text": "The cell releases it."},
    ]
    seen = []
    spans = await prepare_gloss(_AI(["echo"]), units, on_progress=lambda done, total: seen.append((done, total)))
    assert seen == [(1, 1)]
    assert [span["page"] for span in spans] == [0, 0]
    assert spans[0]["unit_id"] == "s1"


@pytest.mark.asyncio
async def test_prepare_gloss_splits_a_batch_that_times_out_and_skips_finished_sentences():
    units = [
        {"id": "s1", "page": 0, "text": "Energy is stored."},
        {"id": "s2", "page": 0, "text": "The cell releases it."},
    ]
    ai = _AI([AIError("Cursor 执行超时，请稍后重试。", retryable=True), "echo", "echo"])
    saved = []
    spans = await prepare_gloss(ai, units, on_batch=saved.extend)
    assert ai.calls == 3
    assert [span["unit_id"] for span in spans] == ["s1", "s2"]
    assert saved == spans

    again = _AI(["echo"])
    skipped = await prepare_gloss(again, units, skip_ids={"s1"})
    assert again.calls == 1
    assert [span["unit_id"] for span in skipped] == ["s2"]


@pytest.mark.asyncio
async def test_prepare_gloss_keeps_a_long_sentence_in_its_own_batch():
    units = [
        {"id": "s1", "page": 0, "text": ("The model stores energy in every cell. " * 16).strip()},
        {"id": "s2", "page": 0, "text": "Next."},
    ]
    seen = []
    spans = await prepare_gloss(_AI(["echo", "echo"]), units, on_progress=lambda done, total: seen.append((done, total)))
    assert seen == [(1, 2), (2, 2)]
    assert [span["unit_id"] for span in spans] == ["s1", "s2"]
