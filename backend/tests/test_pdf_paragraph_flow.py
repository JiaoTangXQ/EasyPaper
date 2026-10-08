import re
from asyncio import CancelledError
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from types import SimpleNamespace

import fitz
import pytest

from app.services.pdf_paragraph_flow import (
    ParagraphFlow,
    TextSlot,
    _joined_source,
    paragraph_groups,
    split_to_slots,
)
from app.services.reader_geometry import recorded_mappings


def slot(index, page, text, *, x=35, top=260, width=350, lines=3, size=10):
    font = fitz.Font("tiro")
    latin = SimpleNamespace(to_unichr=chr, char_width=font.glyph_advance)
    return TextSlot(
        index,
        page,
        text,
        SimpleNamespace(
            x=x, x0=x, x1=x + width, y=top, y0=top - (lines - 1) * size * 1.2, y1=top + size, size=size, brk=lines > 1
        ),
        420,
        300,
        latin,
        font,
        {"{v0}": 10, "{v1}": 10},
    )


def test_three_page_sentence_and_uppercase_continuation_are_one_group():
    slots = [
        slot(0, 0, "The evaluation compares the policies produced by"),
        slot(1, 1, "PPO and GRPO across several training runs to estimate"),
        slot(2, 2, "the expected reward and report the final results."),
    ]
    assert paragraph_groups(slots) == [slots]
    flow = ParagraphFlow()
    calls = []
    target = "The test compares policies from PPO and GRPO across training runs to estimate expected reward and report results."
    flow.translate = lambda text: calls.append(text) or target
    pieces = flow._simplify(slots)
    assert calls == [" ".join(s.text for s in slots)]
    assert " ".join(pieces) == target
    assert all(s.fits(text) for s, text in zip(slots, pieces, strict=True))


@pytest.mark.parametrize(
    "following", ["2 METHODS", "Figure 2: Overview of the model", "A separate experiment starts here."]
)
def test_headings_captions_and_completed_sentences_are_not_joined(following):
    left = "The paragraph ends here." if following.startswith("A separate") else "The paragraph continues with"
    slots = [slot(0, 0, left), slot(1, 1, following)]
    assert paragraph_groups(slots) == [[slots[0]], [slots[1]]]


def test_headers_page_numbers_and_footnotes_do_not_hide_the_continuation():
    slots = [
        slot(0, 0, "RUNNING HEADER", top=285),
        slot(1, 0, "The policy gradient method computes the gradient of the"),
        slot(2, 0, "A footnote explains an unrelated experimental detail.", top=25, size=7),
        slot(3, 0, "1", top=10),
        slot(4, 1, "RUNNING HEADER", top=285),
        slot(5, 1, "expected reward over samples from the policy."),
        slot(6, 1, "2", top=10),
    ]
    groups = paragraph_groups(slots)
    assert [slots[1], slots[5]] in groups
    assert all(len(group) == 1 for group in groups if group[0] != slots[1])


def test_layout_classification_blocks_sentence_case_section_headings():
    first = slot(0, 0, "The analysis continues with")
    heading = slot(1, 1, "Related work", lines=1)
    heading.kind = "title"
    assert paragraph_groups([first, heading]) == [[first], [heading]]


def test_two_columns_join_the_right_column_to_the_next_pages_left_column():
    slots = [
        slot(0, 0, "The left column ends with an incomplete", width=165, top=60),
        slot(1, 0, "The right column ends with another incomplete", x=220, width=165, top=120),
        slot(2, 1, "sentence that continues from the right column.", width=165),
        slot(3, 1, "Unrelated text in the right column.", x=220, width=165),
    ]
    assert [slots[1], slots[2]] in paragraph_groups(slots)
    assert [slots[0]] in paragraph_groups(slots)


def test_nonconsecutive_pages_and_indented_new_paragraphs_are_not_joined():
    first = slot(0, 0, "The policy gradient method computes the")
    skipped = slot(1, 2, "expected reward gradient.")
    assert paragraph_groups([first, skipped]) == [[first], [skipped]]
    indented = slot(2, 1, "A new paragraph discusses a different method.")
    indented.box.x += 20
    assert paragraph_groups([first, indented]) == [[first], [indented]]


def test_standalone_equation_is_a_barrier_but_a_hidden_page_number_is_not():
    first = slot(0, 0, "The definition of the expected reward is", top=160)
    formula = slot(1, 0, "{v0}", top=100)
    formula.literal = "E[R] = 0."
    following = slot(2, 1, "A new paragraph discusses the measured results.")
    assert paragraph_groups([first, formula, following]) == [[first], [formula], [following]]
    formula.literal = "1"
    assert paragraph_groups([first, formula, following]) == [[first, following], [formula]]


def test_different_equations_at_page_edges_are_not_mistaken_for_repeated_headers():
    first = slot(0, 0, "The definition of the expected reward is", top=160)
    bottom_formula = slot(1, 0, "{v0}", top=20, lines=1)
    bottom_formula.literal = "E[R] = 0."
    top_formula = slot(2, 1, "{v0}", top=285, lines=1)
    top_formula.literal = "P(x) = 1."
    following = slot(3, 1, "A new paragraph discusses the measured results.")
    slots = [first, bottom_formula, top_formula, following]
    assert paragraph_groups(slots) == [[s] for s in slots]


def test_formula_namespaces_and_page_ownership_survive_resplitting():
    slots = [
        slot(0, 0, "The method utilizes {v0} and the", width=190, lines=2),
        slot(1, 1, "reward {v0} to compute the gradient.", width=190, lines=2),
    ]
    joined, sources, mappings = _joined_source(slots)
    assert joined == "The method utilizes {v0} and the reward {v1} to compute the gradient."
    target = "The method uses {v0} and reward {v1} to compute the gradient."
    pieces = split_to_slots(target, slots, sources, mappings)
    assert pieces is not None
    assert [Counter(re.findall(r"\{v\d+\}", piece)) for piece in pieces] == [Counter({"{v0}": 1}), Counter({"{v0}": 1})]
    assert all(s.fits(piece) for s, piece in zip(slots, pieces, strict=True))
    # A reorder that would move a formula to another page cannot be rendered.
    assert (
        split_to_slots("The method uses {v1} and reward {v0} to compute the gradient.", slots, sources, mappings)
        is None
    )


def test_overlong_output_is_never_partially_applied_or_allowed_to_overflow():
    slots = [slot(0, 0, "The model uses", width=60, lines=1), slot(1, 1, "many samples.", width=60, lines=1)]
    _, sources, mappings = _joined_source(slots)
    assert (
        split_to_slots("The model uses many carefully selected additional training samples.", slots, sources, mappings)
        is None
    )


def test_concurrent_document_plans_do_not_share_source_or_targets():
    barrier = Barrier(2)

    def run(subject):
        slots = [slot(0, 0, f"The {subject} method utilizes"), slot(1, 1, "samples to compute the gradient.")]
        flow = ParagraphFlow()

        def rewrite(text):
            barrier.wait(timeout=3)
            return text.replace("utilizes", "uses")

        flow.translate = rewrite
        return " ".join(flow._simplify(slots))

    with ThreadPoolExecutor(2) as pool:
        one, two = list(pool.map(run, ["first", "second"]))
    assert one == "The first method uses samples to compute the gradient."
    assert two == "The second method uses samples to compute the gradient."


def test_cancelled_plan_never_starts_model_requests():
    event = Event()
    event.set()
    flow = ParagraphFlow(cancellation_event=event)
    flow.translate = lambda _: pytest.fail("Cancelled plan called the model")
    with pytest.raises(CancelledError):
        flow.finish({})


def test_reader_maps_a_reflowed_group_across_both_pages():
    sources = ["More formally, the policy gradient", "method computes the expected reward gradient."]
    targets = ["The policy gradient method computes", "the expected reward gradient."]
    source = {"pages": [{}, {}], "units": [{"id": f"s{i}", "page": i, "text": text} for i, text in enumerate(sources)]}
    target = {"pages": [{}, {}], "units": [{"id": f"t{i}", "page": i, "text": text} for i, text in enumerate(targets)]}
    records = [
        {"source": src, "target": dst, "page": str(i), "flow_group": "0"}
        for i, (src, dst) in enumerate(zip(sources, targets, strict=True))
    ]
    assert recorded_mappings(source, target, records) == [
        {"source_ids": ["s0", "s1"], "target_ids": ["t0", "t1"], "method": "translation-record"}
    ]
    # Matching only half a group must not claim page-local semantic equivalence.
    target["units"].pop()
    assert recorded_mappings(source, target, records) == []
