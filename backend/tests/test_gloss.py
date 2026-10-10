import json

import pytest

from app.services.gloss import GlossCoverageError, prepare_gloss, tile_sentence


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


def test_rejects_a_gap_and_a_word_span_that_contains_two_words():
    source = "The model learns quickly."
    with pytest.raises(GlossCoverageError):
        tile_sentence(source, [{"text": "The model", "category": "term", "zh": "该模型", "role": "研究对象"}])
    with pytest.raises(GlossCoverageError):
        tile_sentence(
            source,
            [{"text": "The model learns quickly.", "category": "word", "zh": "整句", "en": "the whole sentence"}],
        )


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
