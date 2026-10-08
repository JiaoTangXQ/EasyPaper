import pytest

from app.services.simplification_guard import (
    guarded_simplification,
    keep_source_label,
    simplify_preserving_fragments,
)


def test_title_expansion_and_placeholder_acknowledgement_cannot_cover_the_page():
    title = "Repo-To-Skill: Distilling GitHub Repositories Into AI4AI Skills"
    assert keep_source_label(title)
    assert guarded_simplification(title, "This paper presents a new method. " * 30) == title
    assert guarded_simplification("{v0}", "I'm ready to help simplify academic English.") == "{v0}"


def test_real_paragraph_rewrite_preserves_numbers_and_formula_placeholders():
    source = "The method utilizes 20 specialized tools and reduces memory usage by 30% {v2}."
    valid = "The method uses 20 special tools and needs 30% less memory {v2}."
    assert guarded_simplification(source, valid) == valid
    assert guarded_simplification(source, valid.replace("30%", "50%")) == source
    assert guarded_simplification(source, valid.replace("{v2}", "")) == source


def test_cross_page_continuation_cannot_be_rewritten_as_a_new_sentence():
    source = (
        "method computes the gradient of the expected reward over rollouts {v0} from the policy {v1} "
        "as the expected score weighted by the reward {v2}:"
    )
    rewritten = (
        "The method calculates how the expected reward changes over rollouts {v0} from the policy {v1}. "
        "It does this as the expected score weighted by the reward {v2}:"
    )
    assert guarded_simplification(source, rewritten) == source


def test_unfinished_sentence_at_page_bottom_must_remain_intact():
    source = "The algorithm utilizes scored outputs to compute updates. More formally, the policy gradient"
    rewritten = "The algorithm uses scored outputs to compute updates. The policy gradient method"
    assert guarded_simplification(source, rewritten) == source
    valid = "The algorithm uses scored outputs to compute updates. More formally, the policy gradient"
    assert guarded_simplification(source, valid) == valid


@pytest.mark.parametrize(
    "prefix,suffix",
    [
        ("method computes the gradient of the expected reward {v0}: ", " More formally, the policy gradient"),
        ("and uses examples from Smith et al. (2026). ", " We use the method of Smith et al."),
        ("{v0} is weighted by the reward. ", " This requires a forward-"),
        ("and uses e.g. 3.14 as its value. ", " Its expected reward is 3.14"),
        ("and cites J. Smith and the U.S. team. ", " The method computes"),
        ("", " The reported result (Smith et al., 2026; e.g. Fig. 2)"),
    ],
)
def test_only_complete_sentences_are_sent_to_model(prefix, suffix):
    complete = "This method utilizes samples to compute the gradient (Smith et al., 2026)."
    simple = "This method uses samples to compute the gradient (Smith et al., 2026)."
    calls = []

    def rewrite(text):
        calls.append(text)
        return simple

    source = prefix + complete + suffix
    assert simplify_preserving_fragments(source, rewrite) == prefix + simple + suffix
    assert calls == [complete]


@pytest.mark.parametrize(
    "source",
    [
        "More formally, the policy gradient",
        "method computes the gradient of the expected reward weighted by the score:",
        "{v0} is the expected reward over rollouts.",
        "1 INTRODUCTION",
    ],
)
def test_fragments_and_labels_do_not_require_model_calls(source):
    def rewrite(_text):
        pytest.fail("An incomplete sentence or label must not be sent to the model")

    assert simplify_preserving_fragments(source, rewrite) == source


def test_rewrite_cannot_drop_the_boundary_before_a_preserved_fragment():
    source = "The method utilizes samples to compute the gradient. More formally, the policy gradient"
    invalid = "The method uses samples to compute the gradient More formally, the policy gradient"
    assert guarded_simplification(source, invalid) == source
