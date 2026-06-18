from __future__ import annotations

import pytest

from app.services.highlighter import HighlightService


@pytest.fixture
def svc():
    service = HighlightService(api_key="x", model="m", base_url="http://example/v1")
    yield service


def end(svc, char, previous, next_char, before=""):
    return svc._is_sentence_end(char, previous, next_char, before)


def test_real_sentence_end(svc):
    # "...model. The next..." — period after a normal word, followed by a space.
    assert end(svc, ".", "l", " ", "This is a model") is True


def test_cjk_terminator_always_ends(svc):
    assert end(svc, "。", "型", "下", "这是一个模型") is True


def test_decimal_number_not_end(svc):
    assert end(svc, ".", "3", "1", "value 3") is False


def test_period_followed_by_nonspace_not_end(svc):
    # e.g. "domain.com" / "e.g.x"
    assert end(svc, ".", "g", "x", "e.g") is False


def test_known_abbreviation_not_end(svc):
    assert end(svc, ".", "l", " ", "reported by Smith et al") is False
    assert end(svc, ".", "g", " ", "as shown in Fig") is False
    assert end(svc, ".", "q", " ", "see Eq") is False


def test_dotted_acronym_not_end(svc):
    # "i.e." / "U.S." — trailing token already contains an internal period.
    assert end(svc, ".", "e", " ", "i.e") is False


def test_single_initial_not_end(svc):
    assert end(svc, ".", "J", " ", "J") is False
